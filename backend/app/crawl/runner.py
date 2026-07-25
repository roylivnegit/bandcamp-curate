"""Drive the frontier to completion.

`process_one` claims and runs a single frontier entry; `run_until_empty` loops
until the frontier drains or a bound is hit. Both are provider-agnostic (they take
a `Fetcher`) and Redis-free, so the CLI and tests can run a full crawl in-process.
The ARQ worker reuses `process_one` per job for the production, throttled path.
"""

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bandcamp.collection_api import CollectionApiClient
from app.bandcamp.follows_api import FollowsApiClient
from app.bandcamp.supporters_api import SupportersApiClient
from app.crawl import frontier
from app.crawl.service import (
    CrawlOutcome,
    Fetcher,
    crawl_album,
    crawl_fan_collection,
    crawl_track,
)
from app.db.models import CrawlFrontier, ProviderUsage
from app.enums import CrawlKind

logger = logging.getLogger("crate_digger.crawl")


async def requests_used(session: AsyncSession) -> int:
    """Count successful provider (Nimble) page fetches logged so far — the budget metric."""
    return (
        await session.execute(
            select(func.count()).select_from(ProviderUsage).where(ProviderUsage.ok.is_(True))
        )
    ).scalar_one()


async def budget_exhausted(session: AsyncSession, max_requests: int | None) -> bool:
    """Whether the cumulative provider-request budget has been reached."""
    if max_requests is None:
        return False
    return await requests_used(session) >= max_requests


async def process_entry(
    session: AsyncSession,
    fetcher: Fetcher,
    entry: CrawlFrontier,
    *,
    seed_url: str | None = None,
    collection_client: CollectionApiClient | None = None,
    follows_client: FollowsApiClient | None = None,
    supporters_client: SupportersApiClient | None = None,
    max_depth: int | None = None,
) -> CrawlOutcome:
    """Run one already-claimed frontier entry by kind. Raises on failure."""
    if entry.kind == CrawlKind.FAN_COLLECTION:
        return await crawl_fan_collection(
            session, fetcher, entry.url,
            is_me=(entry.url == seed_url),
            collection_client=collection_client,
            follows_client=follows_client,
            depth=entry.depth,
            max_depth=max_depth,
        )
    if entry.kind == CrawlKind.ALBUM:
        return await crawl_album(
            session, fetcher, entry.url, depth=entry.depth, max_depth=max_depth,
            supporters_client=supporters_client,
        )
    if entry.kind == CrawlKind.TRACK:
        return await crawl_track(
            session, fetcher, entry.url, depth=entry.depth, max_depth=max_depth,
            supporters_client=supporters_client,
        )
    raise ValueError(f"unsupported crawl kind: {entry.kind}")


async def process_one(
    session: AsyncSession,
    fetcher: Fetcher,
    *,
    seed_url: str | None = None,
    collection_client: CollectionApiClient | None = None,
    follows_client: FollowsApiClient | None = None,
    supporters_client: SupportersApiClient | None = None,
    max_depth: int | None = None,
) -> CrawlOutcome | None:
    """Claim and process a single frontier entry. Returns None if none pending."""
    entry = await frontier.claim_next(session)
    if entry is None:
        return None
    # Capture identity now — after a commit/rollback the instance expires, and
    # re-reading an attribute would trigger an illegal async lazy-load.
    entry_id, url, kind = entry.id, entry.url, entry.kind
    try:
        outcome = await process_entry(
            session, fetcher, entry, seed_url=seed_url,
            collection_client=collection_client, follows_client=follows_client,
            supporters_client=supporters_client, max_depth=max_depth,
        )
    except Exception as exc:  # noqa: BLE001 — record and move on; crawl is resumable
        await session.rollback()
        reloaded = await frontier.get_by_id(session, entry_id)
        if reloaded is not None:
            await frontier.mark_error(session, reloaded, f"{type(exc).__name__}: {exc}")
        logger.warning("crawl failed for %s (%s): %s", url, kind, exc)
        raise
    await frontier.mark_done(session, entry)
    logger.info(
        "crawled %s (%s): items=%d tracks=%d supporters=%d enqueued=%d",
        outcome.url, outcome.kind, outcome.items, outcome.tracks,
        outcome.supporters, outcome.enqueued,
    )
    return outcome


async def run_until_empty(
    sessionmaker: async_sessionmaker[AsyncSession],
    fetcher: Fetcher,
    *,
    seed_url: str | None = None,
    collection_client: CollectionApiClient | None = None,
    follows_client: FollowsApiClient | None = None,
    supporters_client: SupportersApiClient | None = None,
    max_depth: int | None = None,
    max_requests: int | None = None,
    max_iterations: int = 1000,
) -> list[CrawlOutcome]:
    """Process frontier entries until it drains, the request budget is hit, or
    `max_iterations` is reached."""
    outcomes: list[CrawlOutcome] = []
    for _ in range(max_iterations):
        async with sessionmaker() as session:
            if await budget_exhausted(session, max_requests):
                logger.info("request budget reached (%s); stopping", max_requests)
                break
            try:
                outcome = await process_one(
                    session, fetcher, seed_url=seed_url,
                    collection_client=collection_client, follows_client=follows_client,
                    supporters_client=supporters_client, max_depth=max_depth,
                )
            except Exception:  # noqa: BLE001 — already recorded; keep draining
                continue
        if outcome is None:
            break
        outcomes.append(outcome)
    return outcomes
