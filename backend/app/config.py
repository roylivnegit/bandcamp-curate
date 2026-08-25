from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application config, loaded from environment / .env.

    Secrets (notably NIMBLE_API_KEY) are read here and nowhere else. The raw
    key value is never logged or serialized — see `nimble_api_key` usage.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_env: str = "local"
    log_level: str = "INFO"

    # Nimble v2
    nimble_api_key: str = ""
    nimble_base_url: str = "https://sdk.nimbleway.com/v2"
    nimble_country: str = "US"
    nimble_driver: str = "auto"

    # Infra
    database_url: str = "postgresql+asyncpg://crate:crate@localhost:5432/crate"
    redis_url: str = "redis://localhost:6379/0"

    # Connection pool. Must comfortably exceed `crawl_concurrency` or the pool
    # becomes the real concurrency limit — SQLAlchemy's default of 5+10 quietly
    # capped a 50-worker crawl at 15. Against a *direct* managed-Postgres endpoint
    # keep this modest (their connection ceilings are low); a transaction pooler
    # (Neon `-pooler`) takes far more, and `db.url` configures asyncpg for it.
    db_pool_size: int = 20
    db_max_overflow: int = 40
    # Recycle before a managed provider's own idle cutoff closes a pooled
    # connection under us (the classic "connection was closed in the middle of
    # operation" on the next checkout).
    db_pool_recycle_seconds: int = 240

    # Scraper rate limiting (stay well under Nimble's ~83 QPS ceiling)
    scraper_max_qps: float = 30.0
    scraper_max_concurrency: int = 40
    # Per-provider same-request retries on 429/5xx (backoff between each).
    scraper_max_retries: int = 10
    # Route the paginated Bandcamp API calls (collection/wishlist/follows/supporters)
    # through Nimble instead of direct httpx: no 429s under concurrency, but 1 credit
    # per page (vs free direct). Also logged to provider_usage / counted in the budget.
    pagination_via_nimble: bool = True

    # Crawl fan-out bound: max distance from the seed to keep crawling
    # (seed=0 → my albums=1 → their supporters=2 → those supporters' albums=3 …).
    crawl_max_depth: int = 3

    # Safety budget: stop crawling once this many provider (Nimble) page fetches
    # have been logged. Cumulative across runs; a coarse cost cap. Tune later.
    crawl_max_requests: int = 5000

    # Frontier entries crawled in parallel within one slice. A Nimble render takes
    # 3-35s, so a serial drain is almost entirely idle waiting — at 1 this managed
    # ~3 fetches/min against a limiter allowing far more. Each worker holds its own
    # DB session and claims with FOR UPDATE SKIP LOCKED. One entry can issue several
    # fetches (a render plus its pagination), so this multiplies against
    # `scraper_max_concurrency`, which stays the hard ceiling. Raise via env.
    crawl_concurrency: int = 8

    # How long one slice may crawl before handing over to the next job. Bound the
    # slice by TIME, not by entry count: an entry is 1 fetch for an album but up to
    # 11 for a fan collection (render + pagination), so "50 entries" was anywhere
    # from 50 to 550 fetches and blew past `job_timeout` at the top of that range.
    # Seconds are the thing the timeout actually measures.
    crawl_slice_seconds: int = 120

    # Hard bound on ONE frontier entry. The slice deadline is only checked between
    # entries, so a single long entry holds the whole slice open however short the
    # slice budget is — measured at 25-70s uncontended (a render plus sequential
    # supporters pagination) and minutes under concurrency, which is what kept
    # blowing the 600s job_timeout. Exceeding this cancels the entry; its committed
    # pages survive and the claim is reclaimed later as stale.
    crawl_entry_seconds: int = 180

    # Re-curate after each slice so the feed fills in while the crawl runs, rather
    # than appearing all at once at the end. Recommendations are recomputed
    # wholesale in one transaction, so a reader sees the previous set or the new
    # one, never a partial.
    crawl_curate_each_slice: bool = True

    # A `running` scan whose chain hasn't produced a slice in this long is treated
    # as dead (its job was killed) and re-queued. Comfortably over
    # `crawl_slice_seconds` + ARQ's job_timeout so a live-but-slow slice is safe.
    scan_stalled_after_seconds: int = 900

    # Seed (legacy operator-only bootstrap — see scripts/crawl.py)
    bandcamp_fan_url: str = ""

    # Auth: JWT signing secret. Read here and nowhere else, same discipline as
    # nimble_api_key — never logged or serialized.
    auth_secret_key: str = ""
    # How long an issued access token stays valid. Long by default: this is a
    # personal-scale app with no refresh-token flow, so a short TTL would just
    # mean re-logging in constantly. Lower it if that tradeoff changes.
    auth_token_ttl_days: int = 30
    # Shared invite code required at signup (gates who can queue crawls against
    # this deployment's Nimble budget). Empty disables signup entirely.
    auth_invite_code: str = ""
    # The deployed React app's origin, for CORS (the frontend is a separate service).
    frontend_origin: str = "http://localhost:5173"

    # Curation: an item owned by fewer than this many taste-neighbours isn't a
    # recommendation at all. 1 = today's behaviour (no floor) — the right value
    # depends on the co_owners distribution, which only Roy can read locally.
    curation_min_co_owners: int = 1
    # Weight each co-owner by how many of YOUR owned items they also own (a count,
    # never a ratio — see engine._neighbour_overlap for why dividing by collection
    # size would boost under-crawled fans). On by default: at floor 1 this can only
    # reorder the feed, never shrink it.
    curation_weighted_co_owners: bool = True

    @property
    def nimble_configured(self) -> bool:
        return bool(self.nimble_api_key)

    @property
    def auth_configured(self) -> bool:
        return bool(self.auth_secret_key)

    @property
    def cors_origins(self) -> list[str]:
        """Origins allowed to call the API. Blank entries are dropped: a
        dashboard-managed FRONTEND_ORIGIN that's declared but left empty arrives
        as "", and passing [""] to CORSMiddleware matches nothing while looking
        configured — a confusing way to lose every cross-origin request."""
        return [o for o in (self.frontend_origin.strip(),) if o]


@lru_cache
def get_settings() -> Settings:
    return Settings()
