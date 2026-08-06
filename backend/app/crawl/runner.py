"""Drive the frontier to completion.

`process_one` claims and runs a single frontier entry; `run_until_empty` loops
until the frontier drains or a bound is hit. Both are provider-agnostic (they take
a `Fetcher`) and Redis-free, so the CLI and tests can run a full crawl in-process.
The ARQ worker reuses `process_one` per job for the production, throttled path.
"""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bandcamp.collection_api import CollectionApiClient
from app.bandcamp.follows_api import FollowsApiClient
from app.bandcamp.supporters_api import SupportersApiClient
from app.crawl import frontier
from app.crawl.replay import replay_fanout
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


async def _reuse_if_already_crawled(
    session: AsyncSession,
    entry: CrawlFrontier,
    *,
    max_depth: int | None,
    seed_url: str | None,
) -> CrawlOutcome | None:
    """If another scan already crawled this (url, kind), complete it for free.

    The graph is global, so the fetch would tell us nothing new — but the *fan-out*
    would, so we replay that from the stored rows. Skipping the fetch without the
    replay would quietly stop this scan's walk at every page another scan had
    already seen. Returns None when there's nothing to reuse.

    **Never reuses the scan owner's own fan page.** That crawl is not equivalent to
    anyone else's: only an `is_me=True` visit ingests the wishlist and follows, and
    every curation exclusion comes from them. A collector's page is very likely to
    have been crawled already as somebody else's neighbour (with `is_me=False`, so
    no wishlist, no follows) — reusing that would mark the entry DONE, satisfy
    `scan_service._self_crawl_complete`, and curate with no exclusions at all.
    """
    if seed_url is not None and entry.url == seed_url:
        return None  # the owner's own page — must be crawled live, see above
    if not await frontier.completed_elsewhere(
        session, entry.url, entry.kind, scan_id=entry.scan_id
    ):
        return None
    enqueued = 0
    if max_depth is None or entry.depth < max_depth:
        enqueued = await replay_fanout(
            session, entry.url, entry.kind, scan_id=entry.scan_id, depth=entry.depth + 1,
        )
    await session.commit()
    logger.info(
        "reused %s (%s): already crawled by another scan, replayed %d children",
        entry.url, entry.kind, enqueued,
    )
    return CrawlOutcome(url=entry.url, kind=str(entry.kind), enqueued=enqueued, reused=True)


async def process_entry(
    session: AsyncSession,
    fetcher: Fetcher,
    entry: CrawlFrontier,
    *,
    seed_url: str | None = None,
    seed_fan_id: int | None = None,
    collection_client: CollectionApiClient | None = None,
    follows_client: FollowsApiClient | None = None,
    supporters_client: SupportersApiClient | None = None,
    max_depth: int | None = None,
) -> CrawlOutcome:
    """Run one already-claimed frontier entry by kind. Raises on failure."""
    reused = await _reuse_if_already_crawled(
        session, entry, max_depth=max_depth, seed_url=seed_url
    )
    if reused is not None:
        return reused
    if entry.kind == CrawlKind.FAN_COLLECTION:
        return await crawl_fan_collection(
            session, fetcher, entry.url,
            is_me=(entry.url == seed_url),
            collection_client=collection_client,
            follows_client=follows_client,
            depth=entry.depth,
            max_depth=max_depth,
            seed_fan_id=seed_fan_id,
            cursor=entry.cursor,
            entry=entry,  # lets each page commit its own resume bookmark
            scan_id=entry.scan_id,
        )
    if entry.kind == CrawlKind.ALBUM:
        return await crawl_album(
            session, fetcher, entry.url, depth=entry.depth, max_depth=max_depth,
            supporters_client=supporters_client, scan_id=entry.scan_id,
        )
    if entry.kind == CrawlKind.TRACK:
        return await crawl_track(
            session, fetcher, entry.url, depth=entry.depth, max_depth=max_depth,
            supporters_client=supporters_client, scan_id=entry.scan_id,
        )
    raise ValueError(f"unsupported crawl kind: {entry.kind}")


async def process_one(
    session: AsyncSession,
    fetcher: Fetcher,
    *,
    scan_id: int,
    seed_url: str | None = None,
    seed_fan_id: int | None = None,
    collection_client: CollectionApiClient | None = None,
    follows_client: FollowsApiClient | None = None,
    supporters_client: SupportersApiClient | None = None,
    max_depth: int | None = None,
    stale_after: timedelta = frontier.STALE_CLAIM_AFTER,
) -> CrawlOutcome | None:
    """Claim and process a single frontier entry. Returns None if none pending."""
    entry = await frontier.claim_next(session, scan_id=scan_id, stale_after=stale_after)
    if entry is None:
        await session.commit()  # nothing to do — don't sit on a connection
        return None
    # Commit the claim before any fetching. The claim's transaction would otherwise
    # stay open across the whole page render (3-35s), pinning a pooled connection
    # that does nothing — the exact shape that exhausted the pool and killed the
    # crawl on 2026-08-06. Making the claim durable here is also what the stale
    # reclaim in `claim_next` already assumes.
    await session.commit()
    # Capture identity now — after a commit/rollback the instance expires, and
    # re-reading an attribute would trigger an illegal async lazy-load.
    entry_id, url, kind = entry.id, entry.url, entry.kind
    try:
        outcome = await process_entry(
            session, fetcher, entry, seed_url=seed_url, seed_fan_id=seed_fan_id,
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
    if outcome.cursor is not None:
        # Paged out mid-collection. Everything fetched so far is already committed;
        # park the bookmark and let the rest of the frontier have a pass first.
        await frontier.mark_partial(session, entry, outcome.cursor)
    else:
        await frontier.mark_done(session, entry)
    if not outcome.reused:  # reuse logs its own, quieter line
        logger.info(
            "crawled %s (%s): items=%d tracks=%d supporters=%d enqueued=%d "
            "skipped_followed=%d%s",
            outcome.url, outcome.kind, outcome.items, outcome.tracks,
            outcome.supporters, outcome.enqueued, outcome.skipped_followed,
            " [partial — will resume]" if outcome.cursor is not None else "",
        )
    return outcome


async def run_until_empty(
    sessionmaker: async_sessionmaker[AsyncSession],
    fetcher: Fetcher,
    *,
    scan_id: int,
    seed_url: str | None = None,
    seed_fan_id: int | None = None,
    collection_client: CollectionApiClient | None = None,
    follows_client: FollowsApiClient | None = None,
    supporters_client: SupportersApiClient | None = None,
    max_depth: int | None = None,
    max_requests: int | None = None,
    max_iterations: int = 1000,
    concurrency: int = 1,
    stale_after: timedelta = frontier.STALE_CLAIM_AFTER,
) -> list[CrawlOutcome]:
    """Process this scan's frontier entries until it drains, the request budget is
    hit, or `max_iterations` entries have been processed.

    `concurrency` workers claim and crawl in parallel. A Nimble render takes 3-35s,
    so a serial drain spends nearly all of its time waiting: at concurrency 1 this
    managed ~3 fetches/min against a limiter configured for 120+. Each worker owns
    its own `AsyncSession` (they are not safe to share) and claims with
    `FOR UPDATE SKIP LOCKED`, so no two ever take the same entry.

    `seed_fan_id` is the fan the walk is for — its `follows` prune detail crawls of
    already-followed artists/labels deep in the walk (see `crawl_fan_collection`).
    """
    outcomes: list[CrawlOutcome] = []
    remaining = max_iterations
    stop = False

    async def worker() -> None:
        nonlocal remaining, stop
        while True:
            if stop or remaining <= 0:
                return
            remaining -= 1  # reserve a slot before awaiting anything
            async with sessionmaker() as session:
                if await budget_exhausted(session, max_requests):
                    logger.info("request budget reached (%s); stopping", max_requests)
                    stop = True
                    return
                try:
                    outcome = await process_one(
                        session, fetcher, seed_url=seed_url, seed_fan_id=seed_fan_id,
                        collection_client=collection_client, follows_client=follows_client,
                        supporters_client=supporters_client, max_depth=max_depth,
                        scan_id=scan_id, stale_after=stale_after,
                    )
                except Exception:  # noqa: BLE001 — already recorded; keep draining
                    continue
            if outcome is None:
                # Nothing claimable *right now*. Other workers may still be adding
                # children, but stopping here keeps the slice bounded — the caller
                # loops again if there's more.
                return
            outcomes.append(outcome)

    if concurrency <= 1:
        await worker()
    else:
        await asyncio.gather(*(worker() for _ in range(concurrency)))
    return outcomes
