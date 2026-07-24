"""ARQ worker — the production, throttled crawl path.

Run with:  arq app.worker.WorkerSettings   (needs Redis + Postgres up)

Jobs are intentionally tiny: `crawl_next` processes exactly one frontier entry
through the shared rate-limited `ScraperGateway`, then re-enqueues itself while
work remains — so the whole crawl is a self-perpetuating chain of small, retryable
jobs rather than one long-running task. `seed_crawl` primes the frontier from
BANDCAMP_FAN_URL and kicks off the chain.

The crawl logic lives in `app.crawl` (Redis-free and unit-tested); this module is
just the ARQ adaptor — building the gateway/sessionmaker once on startup and
mapping jobs onto `runner.process_one`.
"""

import logging
from typing import Any

from arq.connections import RedisSettings

from app.config import get_settings
from app.crawl import frontier, runner
from app.crawl.seed import seed_fan_collection
from app.crawl.service import build_pagination_clients
from app.db.session import get_sessionmaker
from app.scraping.factory import build_gateway

logger = logging.getLogger("crate_digger.worker")


async def on_startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    ctx["settings"] = settings
    ctx["sessionmaker"] = get_sessionmaker()
    ctx["gateway"] = build_gateway(settings, sessionmaker=ctx["sessionmaker"])
    col, fol, sup = build_pagination_clients(
        ctx["gateway"], via_nimble=settings.pagination_via_nimble
    )
    ctx["collection_client"] = col
    ctx["follows_client"] = fol
    ctx["supporters_client"] = sup
    ctx["seed_url"] = settings.bandcamp_fan_url
    ctx["max_depth"] = settings.crawl_max_depth
    ctx["max_requests"] = settings.crawl_max_requests


async def seed_crawl(ctx: dict[str, Any], url: str | None = None) -> str:
    """Enqueue the seed fan collection and start the crawl chain."""
    async with ctx["sessionmaker"]() as session:
        seed_url = await seed_fan_collection(session, url, settings=ctx["settings"])
    await ctx["redis"].enqueue_job("crawl_next")
    logger.info("seeded crawl from %s", seed_url)
    return seed_url


async def crawl_next(ctx: dict[str, Any]) -> bool:
    """Process one frontier entry; re-enqueue self while work + budget remain."""
    max_requests = ctx.get("max_requests")
    async with ctx["sessionmaker"]() as session:
        if await runner.budget_exhausted(session, max_requests):
            logger.info("request budget reached (%s); halting crawl chain", max_requests)
            return False
        try:
            outcome = await runner.process_one(
                session, ctx["gateway"], seed_url=ctx.get("seed_url"),
                collection_client=ctx.get("collection_client"),
                follows_client=ctx.get("follows_client"),
                supporters_client=ctx.get("supporters_client"),
                max_depth=ctx.get("max_depth"),
            )
        except Exception:  # noqa: BLE001 — already recorded on the frontier
            outcome = None
        remaining = await frontier.pending_count(session)
        over_budget = await runner.budget_exhausted(session, max_requests)

    if remaining > 0 and not over_budget:
        await ctx["redis"].enqueue_job("crawl_next")
    return outcome is not None


class WorkerSettings:
    functions = [seed_crawl, crawl_next]
    on_startup = on_startup
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 4  # keep concurrency modest; the RateLimiter is the real throttle
    job_timeout = 300
