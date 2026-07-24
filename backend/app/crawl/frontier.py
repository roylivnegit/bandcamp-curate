"""The crawl frontier — a resumable work queue backed by `crawl_frontier`.

Rows are unique on (url, kind), so enqueueing the same target twice is a no-op:
each fan collection and album page is crawled at most once. `claim_next` atomically
moves the oldest eligible PENDING row to IN_PROGRESS; `mark_done`/`mark_error`
close it out. This is deliberately simple (single-dispatcher friendly); a
`SELECT ... FOR UPDATE SKIP LOCKED` claim can replace it when we run workers
concurrently against Postgres.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CrawlFrontier
from app.enums import CrawlKind, CrawlStatus


async def enqueue(
    session: AsyncSession,
    url: str,
    kind: CrawlKind | str,
    *,
    priority: int = 0,
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
            url=url, kind=kind, status=CrawlStatus.PENDING, priority=priority
        )
    )
    await session.flush()
    return True


async def claim_next(
    session: AsyncSession, kinds: list[CrawlKind | str] | None = None
) -> CrawlFrontier | None:
    """Claim the highest-priority, oldest PENDING row and mark it IN_PROGRESS."""
    stmt = select(CrawlFrontier).where(CrawlFrontier.status == CrawlStatus.PENDING)
    if kinds:
        stmt = stmt.where(CrawlFrontier.kind.in_([str(k) for k in kinds]))
    stmt = stmt.order_by(
        CrawlFrontier.priority.desc(), CrawlFrontier.id.asc()
    ).limit(1)

    entry = (await session.execute(stmt)).scalar_one_or_none()
    if entry is None:
        return None
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
    await session.commit()


async def mark_error(session: AsyncSession, entry: CrawlFrontier, error: str) -> None:
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
