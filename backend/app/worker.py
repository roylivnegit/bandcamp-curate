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

`seed_crawl`/`crawl_next` are legacy, operator-only tooling from the single-tenant
era — they still key off the global BANDCAMP_FAN_URL. Every signed-up user's
collection is onboarded through `scan_service.run_scan`'s `kind=collection`
branch instead (dispatched by `poll_scans` below, same as any other scan).
"""

import logging
from typing import Any

from arq import cron
from arq.connections import RedisSettings

from app.config import get_settings
from app.crawl import frontier, runner, scan_service
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
    ctx["concurrency"] = settings.crawl_concurrency


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


async def run_scan(ctx: dict[str, Any], scan_id: int) -> str:
    """Crawl ONE slice of a scan, then re-enqueue itself while work remains.

    A scan can span tens of thousands of frontier entries — hours of crawling —
    which is far longer than any sane `job_timeout`. Draining it inside a single
    job is what killed two scans on 2026-08-06. So a scan is a *chain* of short
    jobs instead: each slice is bounded and independently durable, the chain
    survives worker restarts, and the UI sees progress as it goes (the frontend
    already polls `scan.status` while a scan is in flight).

    Same self-perpetuating shape as the legacy `crawl_next` chain above.
    """
    try:
        more = await scan_service.advance_scan(
            ctx["sessionmaker"], ctx["gateway"], scan_id,
            collection_client=ctx.get("collection_client"),
            follows_client=ctx.get("follows_client"),
            supporters_client=ctx.get("supporters_client"),
            max_depth=ctx.get("max_depth"), max_requests=ctx.get("max_requests"),
            concurrency=ctx.get("concurrency", 1),
        )
    except Exception as exc:  # noqa: BLE001 — surface it on the scan, then re-raise
        await scan_service.fail_scan(ctx["sessionmaker"], scan_id, exc)
        raise

    if more:
        await ctx["redis"].enqueue_job("run_scan", scan_id)
        return f"scan {scan_id}: slice done, more to crawl"

    try:
        await scan_service.finalize_scan(ctx["sessionmaker"], scan_id)
    except Exception as exc:  # noqa: BLE001 — e.g. incomplete exclusions
        await scan_service.fail_scan(ctx["sessionmaker"], scan_id, exc)
        raise
    return f"scan {scan_id} complete"


async def poll_scans(ctx: dict[str, Any]) -> int:
    """Cron: claim any `queued` scans and dispatch a `run_scan` job for each.
    This is how the UI (cloud) triggers a crawl that executes here (the PC)."""
    async with ctx["sessionmaker"]() as session:
        ids = await scan_service.claim_queued_scans(session)
    for scan_id in ids:
        await ctx["redis"].enqueue_job("run_scan", scan_id)
    if ids:
        logger.info("dispatched %d queued scan(s): %s", len(ids), ids)
    return len(ids)


class WorkerSettings:
    functions = [seed_crawl, crawl_next, run_scan]
    cron_jobs = [cron(poll_scans, second={0, 30}, run_at_startup=True)]
    on_startup = on_startup
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 4  # keep concurrency modest; the RateLimiter is the real throttle
    job_timeout = 600  # a scan crawl can take a while
