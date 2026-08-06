"""Scan orchestration: create scans from seed URLs and run them.

A scan is a named discovery run seeded by album and/or track URLs, any mix.
`run_scan` enqueues the scan's seeds into **its own** frontier queue, drains it
(bounded by depth + the request budget, and pruned of detail crawls for artists
the owner already follows), resolves each seed to its ingested album/track, then
curates that scan.

The *queue* is per-scan; the *graph* is not. Bands, albums, tracks and supporters
stay global, and reaching a page another scan already crawled costs no fetch — the
fan-out is replayed from the stored rows instead (`app.crawl.replay`). Draining
runs as a chain of short slices (`advance_scan`), each processing up to
`max(SCAN_SLICE_ENTRIES, crawl_concurrency)` entries with that many crawls in
flight at once — a slice must offer at least one entry per worker or the workers
starve, so raising concurrency raises the slice with it.
"""

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.crawl import frontier, runner
from app.crawl.service import Fetcher
from app.db.models import Album, CrawlFrontier, Scan, ScanSeed, Track, User
from app.enums import CrawlKind, CrawlStatus, ItemType, ScanKind, ScanStatus

logger = logging.getLogger("crate_digger.scan")

SEED_PRIORITY = 90  # below the owner's own fan page, above ordinary discovery
SELF_FAN_PRIORITY = 100  # the owner's own collection drains first (cf. seed.SEED_PRIORITY)

# FLOOR on the frontier entries one slice may process — `advance_scan` raises it
# to `crawl_concurrency` when that's larger, since a slice offering fewer entries
# than there are workers just leaves workers idle. Each slice is a whole ARQ job,
# so this is what keeps jobs short; the frontier holds tens of thousands of
# entries and draining it inside one job is what used to blow past `job_timeout`.
# Parallelism is what keeps a bigger slice short: 50 entries at 50-way concurrency
# is one ~30s round, not 50 sequential fetches.
SCAN_SLICE_ENTRIES = 10

# Backstop on the chain so a bug can't schedule slices forever. At 10 entries each
# that's 100k entries — far past any real scan, which stops on the credit budget.
MAX_SCAN_SLICES = 10_000

# A Bandcamp album/track URL: any host, path starting /album/<slug> or /track/<slug>.
_SEED_RE = re.compile(r"^(https?://[^/]+/(album|track)/[^/?#]+)", re.IGNORECASE)


def parse_seed_url(url: str) -> tuple[str, str]:
    """(clean_url, seed_type) for a Bandcamp album/track URL; raises on anything else."""
    m = _SEED_RE.match((url or "").strip())
    if not m:
        raise ValueError(f"not a Bandcamp album or track URL: {url!r}")
    return m.group(1), m.group(2).lower()


async def create_scan(session: AsyncSession, user_id: int, name: str, urls: list[str]) -> Scan:
    """Create a queued custom scan owned by `user_id`, from a list of seed URLs
    (album and/or track, any mix). Deduplicates URLs.

    Raises ValueError on an empty name or no valid seeds."""
    name = (name or "").strip()
    if not name:
        raise ValueError("scan name is required")
    seen: set[str] = set()
    seeds: list[tuple[str, str]] = []
    for u in urls:
        clean, kind = parse_seed_url(u)  # raises on invalid
        if clean not in seen:
            seen.add(clean)
            seeds.append((clean, kind))
    if not seeds:
        raise ValueError("at least one album or track URL is required")

    scan = Scan(
        user_id=user_id, name=name, kind=str(ScanKind.CUSTOM), status=str(ScanStatus.QUEUED)
    )
    session.add(scan)
    await session.flush()
    for clean, kind in seeds:
        session.add(ScanSeed(scan_id=scan.id, url=clean, seed_type=kind))
    await session.commit()
    return scan


async def create_collection_scan(session: AsyncSession, user: User) -> Scan:
    """Create the one queued `collection`-kind scan for a newly signed-up user —
    no `ScanSeed` rows; `run_scan` special-cases this kind to seed from the user's
    own `bandcamp_fan_url` directly instead of walking pre-set seeds."""
    scan = Scan(user_id=user.id, name="My collection", kind=str(ScanKind.COLLECTION),
                status=str(ScanStatus.QUEUED))
    session.add(scan)
    await session.commit()
    return scan


async def claim_queued_scans(session: AsyncSession) -> list[int]:
    """Atomically flip every `queued` scan to `running` and return the claimed ids.
    Run by the poller so concurrent polls never dispatch the same scan twice."""
    result = await session.execute(
        update(Scan)
        .where(Scan.status == str(ScanStatus.QUEUED))
        .values(status=str(ScanStatus.RUNNING))
        .returning(Scan.id)
    )
    ids = [row[0] for row in result.all()]
    await session.commit()
    return ids


async def reclaim_stalled_scans(session: AsyncSession, stalled_after: timedelta) -> list[int]:
    """Re-queue `running` scans whose chain has died. Returns the reclaimed ids.

    A scan runs as a chain of jobs that re-enqueue themselves. If a job is killed —
    ARQ's `job_timeout`, a worker restart, the machine sleeping — nothing is left
    to schedule the next one, and the scan sits `running` forever because the
    poller only ever claims `queued`. That stranded three scans on 2026-08-06 and
    each needed a manual nudge.

    `stats.last_slice_at` is written at the start of every slice, so a `running`
    scan whose heartbeat has gone cold has no chain behind it. Re-queueing is safe
    and cheap: the frontier is resumable, so the new chain picks up exactly where
    the dead one stopped.
    """
    cutoff = datetime.now(UTC) - stalled_after
    running = (
        await session.execute(select(Scan).where(Scan.status == str(ScanStatus.RUNNING)))
    ).scalars().all()

    reclaimed: list[int] = []
    for scan in running:
        beat = (scan.stats or {}).get("last_slice_at")
        if beat is not None:
            try:
                if datetime.fromisoformat(beat) > cutoff:
                    continue  # still warm — a slice is genuinely in flight
            except ValueError:
                pass  # unparseable heartbeat: treat as cold rather than trust it
        scan.status = str(ScanStatus.QUEUED)
        reclaimed.append(scan.id)
    if reclaimed:
        await session.commit()
        logger.warning("re-queued %d stalled scan(s): %s", len(reclaimed), reclaimed)
    return reclaimed


async def _resolve_seeds(session: AsyncSession, scan_id: int) -> None:
    """Point each seed at the album/track that was ingested for its URL."""
    seeds = (
        await session.execute(select(ScanSeed).where(ScanSeed.scan_id == scan_id))
    ).scalars().all()
    for seed in seeds:
        if seed.seed_type == str(ItemType.ALBUM) and seed.resolved_album_id is None:
            album = (
                await session.execute(
                    select(Album).where(Album.url == seed.url).order_by(Album.id.desc())
                )
            ).scalars().first()
            if album is not None:
                seed.resolved_album_id = album.id
        elif seed.seed_type == str(ItemType.TRACK) and seed.resolved_track_id is None:
            track = (
                await session.execute(
                    select(Track).where(Track.url == seed.url).order_by(Track.id.desc())
                )
            ).scalars().first()
            if track is not None:
                seed.resolved_track_id = track.id
    await session.commit()


@dataclass(slots=True)
class ScanPlan:
    """What a slice needs to know, re-derived cheaply before each one."""

    self_url: str | None  # the owner's own fan page, when this scan crawls it
    seed_fan_id: int | None  # the owner's Fan, once their page has been ingested


async def start_scan(sessionmaker: async_sessionmaker[AsyncSession], scan_id: int) -> ScanPlan:
    """Put the scan's work on the frontier. Idempotent and fetch-free — cheap
    enough to re-run before every slice, which is exactly how the chain uses it.

    A `collection` scan enqueues the owner's own fan page at `SELF_FAN_PRIORITY`
    so it drains first; the runner recognises it as `is_me` by URL, which is what
    records the wishlist and follows that gate curation. A `custom` scan enqueues
    its seeds. Both are `frontier.enqueue`, so re-running adds nothing.

    Also counts the slice. The count lives here rather than in either caller so
    that BOTH the blocking runner and the ARQ chain are bounded by the same
    `MAX_SCAN_SLICES` — the chain re-enqueues purely on "more work?", so without a
    persisted counter a perpetually-nonempty frontier would spawn jobs forever and
    leave the scan `running` indefinitely.
    """
    async with sessionmaker() as session:
        scan = await session.get(Scan, scan_id)
        if scan is None:
            raise ValueError("scan not found")
        owner = await session.get(User, scan.user_id)
        if owner is None:
            raise ValueError("scan's owning user not found")

        # A scan that isn't already running is starting fresh — reset the per-run
        # bookkeeping (credit baseline + slice count) rather than continuing a
        # previous run's totals. Re-running via the API sets status back to queued.
        stats = dict(scan.stats or {})
        if scan.status != str(ScanStatus.RUNNING):
            scan.status = str(ScanStatus.RUNNING)
            scan.error = None
            stats = {"credits_at_start": await runner.requests_used(session), "slices_run": 0}
        stats.setdefault("credits_at_start", await runner.requests_used(session))
        stats["slices_run"] = stats.get("slices_run", 0) + 1
        # Heartbeat: a chain whose job was killed leaves the scan `running` with
        # nobody working it, and the poller only claims `queued` — so without a
        # timestamp to age out, the scan sits stranded forever (three times on
        # 2026-08-06). `reclaim_stalled_scans` re-queues on this.
        stats["last_slice_at"] = datetime.now(UTC).isoformat()
        scan.stats = stats
        if stats["slices_run"] > MAX_SCAN_SLICES:
            await session.commit()  # keep the count; the caller marks the scan failed
            raise ValueError(
                f"scan exceeded {MAX_SCAN_SLICES} slices without finishing — "
                "stopping rather than queueing more work"
            )

        self_url: str | None = None
        if scan.kind == str(ScanKind.COLLECTION):
            if not owner.bandcamp_fan_url:
                raise ValueError("no bandcamp_fan_url set for this user")
            self_url = owner.bandcamp_fan_url
            await frontier.enqueue(
                session, self_url, CrawlKind.FAN_COLLECTION,
                scan_id=scan_id, priority=SELF_FAN_PRIORITY, depth=0,
            )

        seeds = (
            await session.execute(select(ScanSeed).where(ScanSeed.scan_id == scan_id))
        ).scalars().all()
        for seed in seeds:
            kind = CrawlKind.ALBUM if seed.seed_type == str(ItemType.ALBUM) else CrawlKind.TRACK
            await frontier.enqueue(
                session, seed.url, kind, scan_id=scan_id, priority=SEED_PRIORITY, depth=0
            )

        await session.commit()
        return ScanPlan(self_url=self_url, seed_fan_id=owner.fan_id)


async def advance_scan(
    sessionmaker: async_sessionmaker[AsyncSession],
    fetcher: Fetcher,
    scan_id: int,
    *,
    collection_client=None,
    follows_client=None,
    supporters_client=None,
    max_depth: int | None = None,
    max_requests: int | None = None,
    slice_entries: int = SCAN_SLICE_ENTRIES,
    concurrency: int = 1,
    slice_seconds: float | None = None,
    curate_each_slice: bool = False,
) -> bool:
    """Crawl ONE bounded slice of this scan. True if more work remains.

    Slices are what keep every job short: the frontier can hold tens of thousands
    of entries, and draining it inside a single job is what used to run past ARQ's
    `job_timeout`. Each slice is independently durable, so the chain can stop or
    restart between any two of them and lose nothing.
    """
    plan = await start_scan(sessionmaker, scan_id)  # idempotent

    # A slice must offer at least as many entries as there are workers, or the
    # workers starve: with slice_entries=10 and concurrency=50, ten crawl and forty
    # return immediately, so the effective parallelism is the slice bound. These
    # two were set in different PRs for different reasons and never reconciled —
    # the slice exists to bound job *duration*, which parallelism already shortens.
    slice_entries = max(slice_entries, concurrency)

    # `seed_fan_id` is fixed for the whole slice, but the owner's Fan doesn't exist
    # until their own page is ingested — so on a first-ever collection scan a
    # multi-entry slice would crawl the rest of itself with the followed-artist
    # prune switched off, spending credits on albums curation will drop anyway.
    # Give that one page a slice to itself; every slice after it has the id.
    entries = 1 if (plan.self_url is not None and plan.seed_fan_id is None) else slice_entries

    outcomes = await runner.run_until_empty(
        sessionmaker, fetcher,
        seed_url=plan.self_url, seed_fan_id=plan.seed_fan_id,
        collection_client=collection_client, follows_client=follows_client,
        supporters_client=supporters_client,
        max_depth=max_depth, max_requests=max_requests,
        max_iterations=entries, max_seconds=slice_seconds,
        scan_id=scan_id, concurrency=concurrency,
    )

    # The owner's own page may have been ingested this slice — link the Fan as soon
    # as it is, since `seed_fan_id` (the followed-artist prune) and curation both
    # key off it. Taken from the outcome rather than matched by URL, which would be
    # fragile: the Fan row is created with the page's own trackpipe_url.
    fan_id = next(
        (o.fan_id for o in outcomes
         if o.kind == str(CrawlKind.FAN_COLLECTION)
         and o.url == plan.self_url and o.fan_id is not None),
        None,
    )
    if fan_id is not None:
        async with sessionmaker() as session:
            scan = await session.get(Scan, scan_id)
            owner = await session.get(User, scan.user_id)
            if owner is not None and owner.fan_id is None:
                owner.fan_id = fan_id
                await session.commit()

    if curate_each_slice:
        await _curate_progress(sessionmaker, scan_id, plan.self_url)

    async with sessionmaker() as session:
        if await runner.budget_exhausted(session, max_requests):
            return False  # out of credits — finalize with what we have
        return await frontier.pending_count(session, scan_id=scan_id) > 0


async def _curate_progress(
    sessionmaker: async_sessionmaker[AsyncSession], scan_id: int, self_url: str | None
) -> None:
    """Re-curate mid-crawl so the feed fills in as the scan runs, not all at once.

    Recommendations are recomputed wholesale inside one transaction, so a reader
    always sees the previous complete set or the new one — never a partial feed.
    Each pass simply scores against more of the graph than the last.

    Skipped while the owner's own collection is still being read: every exclusion
    (owned / wishlisted / followed) comes from that crawl, and showing someone
    records they already own is worse than showing them nothing yet. Same guard
    `finalize_scan` applies — an early feed must not be a wrong one.
    """
    from app.curation.engine import curate  # local import avoids an import cycle

    async with sessionmaker() as session:
        if not await _self_crawl_complete(session, self_url, scan_id=scan_id):
            return
        # Resolve seeds first. A custom scan scores from its *resolved* seed — the
        # album/track row its URL was crawled into — and that only happened at
        # finalize, so every interim curate found no seed, no taste-neighbours, and
        # returned zero. Cheap and idempotent: it only fills fields still NULL.
        await _resolve_seeds(session, scan_id)
    try:
        async with sessionmaker() as session:
            scored = await curate(session, scan_id=scan_id)
        async with sessionmaker() as session:
            scan = await session.get(Scan, scan_id)
            if scan is not None:
                scan.stats = {**(scan.stats or {}), "recommendations": len(scored)}
                await session.commit()
        logger.info("scan %s: %d recommendations so far", scan_id, len(scored))
    except Exception as exc:  # noqa: BLE001 — a progress refresh must never kill the crawl
        logger.warning("scan %s: interim curate failed (crawl continues): %s", scan_id, exc)


async def _self_crawl_complete(
    session: AsyncSession, self_url: str | None, *, scan_id: int
) -> bool:
    """Whether the owner's own fan page has been crawled to the last page.

    Scoped to this scan's own entry: another scan having crawled the same page
    doesn't help here, because a *reused* entry contributes no wishlist/follows
    rows of its own — those come from the live crawl that first read the page.
    """
    if self_url is None:
        return True  # custom scan — exclusions come from an earlier collection scan
    entry = (
        await session.execute(
            select(CrawlFrontier).where(
                CrawlFrontier.scan_id == scan_id,
                CrawlFrontier.url == self_url,
                CrawlFrontier.kind == str(CrawlKind.FAN_COLLECTION),
            )
        )
    ).scalar_one_or_none()
    return entry is not None and entry.status == CrawlStatus.DONE


async def finalize_scan(
    sessionmaker: async_sessionmaker[AsyncSession], scan_id: int
) -> Scan:
    """Resolve seeds, curate, mark the scan done.

    Refuses to curate a `collection` scan whose own fan page isn't fully paged:
    every exclusion (owned / wishlisted / followed) comes from that crawl, so
    curating early would silently surface artists the user already has, with
    nothing in the feed revealing why. The scan errors instead — visible,
    re-runnable, and cheap to resume since its pages are already committed.
    """
    from app.curation.engine import curate  # local import avoids an import cycle

    async with sessionmaker() as session:
        scan = await session.get(Scan, scan_id)
        if scan is None:
            raise ValueError("scan not found")
        owner = await session.get(User, scan.user_id)
        self_url = (
            owner.bandcamp_fan_url
            if owner is not None and scan.kind == str(ScanKind.COLLECTION)
            else None
        )
        if not await _self_crawl_complete(session, self_url, scan_id=scan_id):
            raise ValueError(
                "your collection is only partly crawled (the crawl budget ran out "
                "before it finished); refusing to curate on incomplete exclusions — "
                "raise CRAWL_MAX_REQUESTS and re-run to resume where it stopped"
            )
        credits_at_start = (scan.stats or {}).get("credits_at_start", 0)

    async with sessionmaker() as session:
        await _resolve_seeds(session, scan_id)
    async with sessionmaker() as session:
        scored = await curate(session, scan_id=scan_id)
        used_after = await runner.requests_used(session)

    async with sessionmaker() as session:
        scan = await session.get(Scan, scan_id)
        scan.status = str(ScanStatus.DONE)
        scan.last_run_at = datetime.now(UTC)
        scan.stats = {
            "recommendations": len(scored),
            "credits": used_after - credits_at_start,
        }
        await session.commit()
        await session.refresh(scan)
        return scan


async def fail_scan(
    sessionmaker: async_sessionmaker[AsyncSession], scan_id: int, exc: BaseException
) -> None:
    """Record a failure on the scan. Used by both the blocking runner and the
    chained worker jobs, so a crash in either surfaces the same way in the UI."""
    async with sessionmaker() as session:
        scan = await session.get(Scan, scan_id)
        if scan is not None:
            scan.status = str(ScanStatus.ERROR)
            scan.error = f"{type(exc).__name__}: {exc}"
            await session.commit()
    logger.warning("scan %s failed: %s", scan_id, exc)


async def run_scan(
    sessionmaker: async_sessionmaker[AsyncSession],
    fetcher: Fetcher,
    scan_id: int,
    *,
    collection_client=None,
    follows_client=None,
    supporters_client=None,
    max_depth: int | None = None,
    max_requests: int | None = None,
    max_slices: int = MAX_SCAN_SLICES,
    concurrency: int = 1,
) -> Scan:
    """Run a scan to completion in-process: slice, slice, … then finalize.

    This is the blocking form, for the CLI and tests. Production uses the same
    pieces spread across a chain of short ARQ jobs (`app.worker.run_scan`) so no
    single job can outlive its timeout. Marks the scan running → done (or error),
    recording credits spent + rec count in `scan.stats`.
    """
    effective_slice = max(SCAN_SLICE_ENTRIES, concurrency)  # mirrors advance_scan
    try:
        for _ in range(max_slices):
            more = await advance_scan(
                sessionmaker, fetcher, scan_id,
                collection_client=collection_client, follows_client=follows_client,
                supporters_client=supporters_client,
                max_depth=max_depth, max_requests=max_requests,
                concurrency=concurrency,
            )
            if not more:
                break
        else:
            raise ValueError(
                f"scan still unfinished after {max_slices} slices of up to "
                f"{effective_slice} entries each"
            )
        return await finalize_scan(sessionmaker, scan_id)
    except Exception as exc:  # noqa: BLE001 — record on the scan and surface
        await fail_scan(sessionmaker, scan_id, exc)
        raise
