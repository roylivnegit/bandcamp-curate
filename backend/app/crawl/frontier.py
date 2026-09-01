"""The crawl frontier — a resumable, per-scan work queue backed by `crawl_frontier`.

Rows are unique on (scan_id, url, kind): each scan walks its own subtree, so one
scan is never held up draining work another queued. `claim_next` moves the
highest-priority eligible row to IN_PROGRESS; `mark_done` / `mark_partial` /
`mark_error` close it out. Every entry belongs to exactly one scan, including the
operator chain's (see `crawl.seed`): an unowned row is reached by no query.

Safe for many concurrent claimers: the claim is a compare-and-swap on the status
we just read (plus `FOR UPDATE SKIP LOCKED` on Postgres to avoid the wasted
retry), and `enqueue` treats a duplicate-key collision as "someone else added it".
Both use SAVEPOINTs, so losing a race never discards the caller's pending work.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
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

# How many rows a claimer will try before giving up, when it keeps losing the
# compare-and-swap to other workers. Only bites under heavy contention.
_CLAIM_ATTEMPTS = 8


async def size(session: AsyncSession, scan_id: int) -> int:
    """Total frontier rows (any status) queued so far for one scan — the basis
    for the secondary fan-out cap (`Settings.crawl_max_frontier_size`), which
    bounds crawl width independently of depth."""
    return (
        await session.execute(
            select(func.count())
            .select_from(CrawlFrontier)
            .where(CrawlFrontier.scan_id == scan_id)
        )
    ).scalar_one()


async def enqueue(
    session: AsyncSession,
    url: str,
    kind: CrawlKind | str,
    *,
    scan_id: int,
    priority: int = 0,
    depth: int = 0,
    max_frontier_size: int | None = None,
) -> bool:
    """Add a (scan_id, url, kind) to the frontier if absent. True if newly added.

    Race-safe: concurrent crawlers routinely discover the same album at the same
    moment, so a lost check-then-insert race is normal, not exotic. The unique
    constraint is the real arbiter and an IntegrityError just means "someone else
    added it" — the same answer as finding it in the select.

    `max_frontier_size` caps the scan's TOTAL rows (any status) — a secondary
    fan-out bound independent of `depth`, since depth 3 on one popular album can
    still fan out very wide. Defaults to `Settings.crawl_max_frontier_size` (None
    = unbounded) so every call site — the live crawl, the cross-scan replay path,
    a scan's own seeding — sees the same bound with no argument passed; tests
    override explicitly. The check is a plain COUNT before insert, so under
    concurrency a handful of entries can land past the cap — a soft bound, not a
    hard guarantee, same tradeoff as the rest of the frontier's dedup.
    """
    if max_frontier_size is None:
        max_frontier_size = get_settings().crawl_max_frontier_size
    kind = str(kind)
    existing = (
        await session.execute(
            select(CrawlFrontier).where(
                CrawlFrontier.scan_id == scan_id,
                CrawlFrontier.url == url,
                CrawlFrontier.kind == kind,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False
    if max_frontier_size is not None:
        current = await size(session, scan_id)
        if current >= max_frontier_size:
            logger.debug(
                "not enqueuing %s (%s): scan %d already has %d/%d frontier rows",
                url, kind, scan_id, current, max_frontier_size,
            )
            return False
    try:
        # SAVEPOINT, not the outer transaction: the caller has a page's worth of
        # ingested rows pending in this same session, and losing those to a
        # duplicate-URL race would be a far worse bug than the one we're guarding.
        async with session.begin_nested():
            session.add(
                CrawlFrontier(
                    scan_id=scan_id, url=url, kind=kind,
                    status=CrawlStatus.PENDING, priority=priority, depth=depth,
                )
            )
            await session.flush()
    except IntegrityError:
        # Only a duplicate is benign. A NOT NULL or bad-FK violation must NOT be
        # read as "already queued" — that silently drops work and looks like a
        # no-op. Re-select: present ⇒ we lost the race; absent ⇒ the error is real.
        raced = (
            await session.execute(
                select(CrawlFrontier).where(
                    CrawlFrontier.scan_id == scan_id,
                    CrawlFrontier.url == url,
                    CrawlFrontier.kind == kind,
                )
            )
        ).scalar_one_or_none()
        if raced is None:
            raise
        return False
    return True


async def claim_next(
    session: AsyncSession,
    kinds: list[CrawlKind | str] | None = None,
    *,
    scan_id: int,
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

    `scan_id` scopes the claim to one scan's own subtree — required, since every
    entry belongs to exactly one scan.

    Concurrency-safe on Postgres via `FOR UPDATE SKIP LOCKED`: many crawlers claim
    at once, and two of them landing on the same row would crawl it twice and pay
    twice. SQLite has no such clause, but nothing runs it concurrently there.
    """
    cutoff = datetime.now(UTC) - stale_after
    stmt = select(CrawlFrontier).where(
        CrawlFrontier.scan_id == scan_id,
        or_(
            CrawlFrontier.status == CrawlStatus.PENDING,
            and_(
                CrawlFrontier.status == CrawlStatus.IN_PROGRESS,
                CrawlFrontier.updated_at < cutoff,
            ),
        ),
    )
    if kinds:
        stmt = stmt.where(CrawlFrontier.kind.in_([str(k) for k in kinds]))
    stmt = stmt.order_by(
        CrawlFrontier.priority.desc(), CrawlFrontier.attempts.asc(), CrawlFrontier.id.asc()
    ).limit(1)
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        # Lets concurrent claimers skip past a row someone else is taking rather
        # than queue behind it. An optimisation — correctness is the CAS below.
        stmt = stmt.with_for_update(skip_locked=True)

    for _ in range(_CLAIM_ATTEMPTS):
        entry = (await session.execute(stmt)).scalar_one_or_none()
        if entry is None:
            return None
        was_stale = entry.status == CrawlStatus.IN_PROGRESS
        # Compare-and-swap on the status we just read. This, not SKIP LOCKED, is
        # what makes the claim exclusive: SKIP LOCKED is Postgres-only, and two
        # workers reading the same row then both writing IN_PROGRESS would crawl
        # it twice and pay twice. Only the worker whose UPDATE matches wins.
        result = await session.execute(
            update(CrawlFrontier)
            .where(CrawlFrontier.id == entry.id, CrawlFrontier.status == entry.status)
            .values(status=CrawlStatus.IN_PROGRESS, attempts=CrawlFrontier.attempts + 1)
        )
        if result.rowcount == 1:
            await session.refresh(entry)
            if was_stale:
                logger.warning(
                    "reclaimed stale in-progress entry %s (%s)", entry.url, entry.kind
                )
            return entry
        session.expire(entry)  # lost the race — look for another
    return None


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


async def mark_retryable(session: AsyncSession, entry: CrawlFrontier, error: str) -> None:
    """Return an entry to the queue after a recoverable failure, keeping `cursor`.

    Distinct from leaving it IN_PROGRESS: `pending_count` only sees PENDING, and
    that is what tells the scan chain whether work remains. An entry parked
    IN_PROGRESS is invisible to it, so the scan finalizes, the chain stops, and
    nothing ever calls `claim_next` again to trigger the stale reclaim — the work
    isn't deferred, it's abandoned, and the scan reports done without it.

    `attempts` (already bumped by the claim) sorts it behind everything on an
    earlier pass, which is the backoff.
    """
    entry.status = CrawlStatus.PENDING
    entry.last_error = error[:2000]
    await session.commit()


async def mark_error(session: AsyncSession, entry: CrawlFrontier, error: str) -> None:
    """Record a failure. Deliberately leaves `cursor` intact: the pages already
    ingested are committed, so if the entry is ever re-run it must resume from the
    bookmark rather than re-buying them."""
    entry.status = CrawlStatus.ERROR
    entry.last_error = error[:2000]
    await session.commit()


async def pending_count(
    session: AsyncSession,
    kind: CrawlKind | str | None = None,
    *,
    scan_id: int,
) -> int:
    """PENDING entries for one scan."""
    from sqlalchemy import func

    stmt = select(func.count()).select_from(CrawlFrontier).where(
        CrawlFrontier.scan_id == scan_id,
        CrawlFrontier.status == CrawlStatus.PENDING,
    )
    if kind is not None:
        stmt = stmt.where(CrawlFrontier.kind == str(kind))
    return (await session.execute(stmt)).scalar_one()


async def completed_elsewhere(
    session: AsyncSession, url: str, kind: CrawlKind | str, *, scan_id: int
) -> bool:
    """Whether some OTHER scan already crawled this (url, kind) to completion.

    The graph is global, so re-fetching a page another scan already read buys
    nothing but a Nimble credit. The caller completes the entry without fetching
    and replays its fan-out from the stored rows instead (`app.crawl.replay`) —
    skipping the fetch without that would silently truncate this scan's walk.
    """
    return (
        await session.execute(
            select(CrawlFrontier.id).where(
                CrawlFrontier.url == url,
                CrawlFrontier.kind == str(kind),
                CrawlFrontier.scan_id != scan_id,
                CrawlFrontier.status == CrawlStatus.DONE,
            ).limit(1)
        )
    ).scalar_one_or_none() is not None
