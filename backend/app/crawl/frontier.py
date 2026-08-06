"""The crawl frontier — a resumable work queue backed by `crawl_frontier`.

Rows are unique on (url, kind), so enqueueing the same target twice is a no-op:
each fan collection and album page is crawled at most once. `claim_next` atomically
moves the oldest eligible PENDING row to IN_PROGRESS; `mark_done`/`mark_error`
close it out. This is deliberately simple (single-dispatcher friendly); a
`SELECT ... FOR UPDATE SKIP LOCKED` claim can replace it when we run workers
concurrently against Postgres.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CrawlFrontier
from app.enums import CrawlKind, CrawlStatus

logger = logging.getLogger("crate_digger.crawl")

# How long an IN_PROGRESS claim may sit untouched before another claim may take it.
#
# A visit commits after every page, and that commit also persists the claim — so a
# process killed mid-visit (ARQ's 600s job_timeout, a container restart, SIGKILL)
# leaves the row IN_PROGRESS with no one working it. Without recovery those pages
# are unreachable forever, because a plain claim only looks at PENDING. Comfortably
# longer than `job_timeout` so a *live* visit is never stolen from itself.
STALE_CLAIM_AFTER = timedelta(minutes=30)


async def enqueue(
    session: AsyncSession,
    url: str,
    kind: CrawlKind | str,
    *,
    priority: int = 0,
    depth: int = 0,
) -> bool:
    """Add a (url, kind) to the frontier if absent. Returns True if newly added."""
    kind = str(kind)
    existing = (
        await session.execute(
            select(CrawlFrontier).where(
                CrawlFrontier.url == url, CrawlFrontier.kind == kind
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False
    session.add(
        CrawlFrontier(
            url=url, kind=kind, status=CrawlStatus.PENDING, priority=priority, depth=depth
        )
    )
    await session.flush()
    return True


async def claim_next(
    session: AsyncSession,
    kinds: list[CrawlKind | str] | None = None,
    *,
    stale_after: timedelta = STALE_CLAIM_AFTER,
) -> CrawlFrontier | None:
    """Claim the highest-priority, least-visited, oldest eligible row → IN_PROGRESS.

    Eligible = PENDING, **or** IN_PROGRESS and untouched for `stale_after` — a
    claim abandoned by a killed process (see `STALE_CLAIM_AFTER`). Without that
    second case a crash mid-visit would strand the entry forever, since the
    per-page commit makes its IN_PROGRESS durable.

    `attempts` sits between priority and id so the queue sweeps in **passes**: a
    fan collection too big to page in one visit is parked back as PENDING with a
    cursor (see `mark_partial`), and its higher `attempts` puts it behind every
    entry still on its first visit. So one pass gives every collection a bounded
    slice before any of them gets a second — rather than one whale monopolising
    the crawl until it finishes.
    """
    cutoff = datetime.now(UTC) - stale_after
    stmt = select(CrawlFrontier).where(
        or_(
            CrawlFrontier.status == CrawlStatus.PENDING,
            and_(
                CrawlFrontier.status == CrawlStatus.IN_PROGRESS,
                CrawlFrontier.updated_at < cutoff,
            ),
        )
    )
    if kinds:
        stmt = stmt.where(CrawlFrontier.kind.in_([str(k) for k in kinds]))
    stmt = stmt.order_by(
        CrawlFrontier.priority.desc(), CrawlFrontier.attempts.asc(), CrawlFrontier.id.asc()
    ).limit(1)

    entry = (await session.execute(stmt)).scalar_one_or_none()
    if entry is None:
        return None
    if entry.status == CrawlStatus.IN_PROGRESS:
        logger.warning(
            "reclaiming stale in-progress entry %s (%s), untouched since %s",
            entry.url, entry.kind, entry.updated_at,
        )
    entry.status = CrawlStatus.IN_PROGRESS
    entry.attempts += 1
    await session.flush()
    return entry


async def get_by_id(session: AsyncSession, entry_id: int) -> CrawlFrontier | None:
    return (
        await session.execute(
            select(CrawlFrontier).where(CrawlFrontier.id == entry_id)
        )
    ).scalar_one_or_none()


async def mark_done(session: AsyncSession, entry: CrawlFrontier) -> None:
    entry.status = CrawlStatus.DONE
    entry.last_error = None
    entry.cursor = None  # fully paged; nothing left to resume from
    await session.commit()


async def mark_partial(
    session: AsyncSession, entry: CrawlFrontier, cursor: dict
) -> None:
    """Park a partially-paged entry: back to PENDING, carrying `cursor`.

    The work already ingested is committed and stays committed — this only
    records where to pick up. `attempts` (bumped by the claim) puts the entry
    behind everything on an earlier pass, so the crawl sweeps broadly instead of
    draining one huge collection to the end before touching anything else.
    """
    entry.status = CrawlStatus.PENDING
    entry.last_error = None
    entry.cursor = cursor
    await session.commit()


async def mark_error(session: AsyncSession, entry: CrawlFrontier, error: str) -> None:
    """Record a failure. Deliberately leaves `cursor` intact: the pages already
    ingested are committed, so if the entry is ever re-run it must resume from the
    bookmark rather than re-buying them."""
    entry.status = CrawlStatus.ERROR
    entry.last_error = error[:2000]
    await session.commit()


async def pending_count(
    session: AsyncSession, kind: CrawlKind | str | None = None
) -> int:
    from sqlalchemy import func

    stmt = select(func.count()).select_from(CrawlFrontier).where(
        CrawlFrontier.status == CrawlStatus.PENDING
    )
    if kind is not None:
        stmt = stmt.where(CrawlFrontier.kind == str(kind))
    return (await session.execute(stmt)).scalar_one()
