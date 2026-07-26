"""Scan orchestration: create scans from seed URLs and run them.

A scan is a named discovery run seeded by album and/or track URLs, any mix.
`run_scan` enqueues the scan's seeds into the shared frontier, drains it (bounded
by depth + the global request budget), resolves each seed to its ingested
album/track, then curates that scan. The frontier/graph is shared across scans;
only the seeds and resulting recommendations are per-scan.
"""

import logging
import re
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.crawl import frontier, runner
from app.crawl.service import Fetcher, crawl_fan_collection
from app.db.models import Album, Scan, ScanSeed, Track, User
from app.enums import CrawlKind, ItemType, ScanKind, ScanStatus

logger = logging.getLogger("crate_digger.scan")

SEED_PRIORITY = 90  # below the is_me fan seed (100), above ordinary discovery

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
) -> Scan:
    """Crawl a scan's seeds, drain the frontier, resolve seeds, curate the scan.

    Marks the scan running → done (or error), recording credits spent + rec count
    in `scan.stats`. Idempotent-ish: already-crawled seeds aren't re-fetched (the
    frontier dedups on url), but the scan is always re-curated."""
    from app.curation.engine import curate  # local import avoids an import cycle

    async with sessionmaker() as session:
        scan = await session.get(Scan, scan_id)
        if scan is None:
            raise ValueError("scan not found")
        scan.status = str(ScanStatus.RUNNING)
        scan.error = None
        await session.commit()
        seeds = (
            await session.execute(select(ScanSeed).where(ScanSeed.scan_id == scan_id))
        ).scalars().all()
        seed_urls = [(s.url, s.seed_type) for s in seeds]
        used_before = await runner.requests_used(session)
        scan_kind, scan_user_id = scan.kind, scan.user_id

    try:
        # A `collection` scan has no ScanSeed rows — it seeds from the owning
        # user's own Bandcamp fan page directly (their collection/wishlist/follows
        # + owned albums enqueued at depth 1), then falls into the same
        # frontier-drain + curate steps as any custom scan below.
        if scan_kind == str(ScanKind.COLLECTION):
            async with sessionmaker() as session:
                user = await session.get(User, scan_user_id)
                if user is None:
                    raise ValueError("scan's owning user not found")
                if not user.bandcamp_fan_url:
                    raise ValueError("no bandcamp_fan_url set for this user")
                outcome = await crawl_fan_collection(
                    session, fetcher, user.bandcamp_fan_url, is_me=True,
                    collection_client=collection_client, follows_client=follows_client,
                    depth=0, max_depth=max_depth,
                )
                if outcome.fan_id is not None:
                    user.fan_id = outcome.fan_id
                await session.commit()

        # Enqueue seeds at the frontier (dedup'd), then drain.
        async with sessionmaker() as session:
            for url, seed_type in seed_urls:
                if seed_type == str(ItemType.ALBUM):
                    await frontier.enqueue(
                        session, url, CrawlKind.ALBUM, priority=SEED_PRIORITY, depth=0
                    )
                elif seed_type == str(ItemType.TRACK):
                    await frontier.enqueue(
                        session, url, CrawlKind.TRACK, priority=SEED_PRIORITY, depth=0
                    )
            await session.commit()

        await runner.run_until_empty(
            sessionmaker, fetcher,
            collection_client=collection_client, follows_client=follows_client,
            supporters_client=supporters_client,
            max_depth=max_depth, max_requests=max_requests,
        )
        async with sessionmaker() as session:
            await _resolve_seeds(session, scan_id)
        async with sessionmaker() as session:
            scored = await curate(session, scan_id=scan_id)
            used_after = await runner.requests_used(session)
    except Exception as exc:  # noqa: BLE001 — record on the scan and surface
        async with sessionmaker() as session:
            scan = await session.get(Scan, scan_id)
            scan.status = str(ScanStatus.ERROR)
            scan.error = f"{type(exc).__name__}: {exc}"
            await session.commit()
        logger.warning("scan %s failed: %s", scan_id, exc)
        raise

    async with sessionmaker() as session:
        scan = await session.get(Scan, scan_id)
        scan.status = str(ScanStatus.DONE)
        scan.last_run_at = datetime.now(UTC)
        scan.stats = {"recommendations": len(scored), "credits": used_after - used_before}
        await session.commit()
        await session.refresh(scan)
        return scan
