"""Seed the crawl from your own Bandcamp fan page (`BANDCAMP_FAN_URL`).

The seed is a high-priority FAN_COLLECTION so it drains first; the runner marks it
`is_me` by matching the URL, which is what records your follows (see
`ingest_fan_collection`). Everything else is discovered from there.

Legacy, operator-only: predates per-user scans, and still keys off the single
global `BANDCAMP_FAN_URL`. It now has to name a scan like everything else — the
frontier has no unowned rows — so it attaches to the operator's own collection
scan, which is the walk these entries belong to anyway.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.crawl.frontier import enqueue
from app.db.models import Scan
from app.enums import CrawlKind, ScanKind

SEED_PRIORITY = 100


async def operator_scan_id(session: AsyncSession) -> int:
    """The scan the legacy operator chain crawls into: the earliest collection scan.

    Raises if there isn't one. Failing here beats the alternative — inventing a
    placeholder owner, or (as before) writing rows no scan can ever reach.
    """
    scan_id = (
        await session.execute(
            select(Scan.id)
            .where(Scan.kind == str(ScanKind.COLLECTION))
            .order_by(Scan.id)
            .limit(1)
        )
    ).scalars().first()
    if scan_id is None:
        raise ValueError(
            "no collection scan exists to crawl into — sign up (which creates one) "
            "or run a collection scan first. Every frontier entry needs an owner."
        )
    return scan_id


async def seed_fan_collection(
    session: AsyncSession,
    url: str | None = None,
    *,
    settings: Settings | None = None,
    scan_id: int | None = None,
) -> str:
    """Enqueue the seed fan collection. Returns the seeded URL.

    `scan_id` defaults to the operator's collection scan (`operator_scan_id`).
    """
    settings = settings or get_settings()
    seed_url = url or settings.bandcamp_fan_url
    if not seed_url:
        raise ValueError("no seed URL: set BANDCAMP_FAN_URL or pass url=")
    if scan_id is None:
        scan_id = await operator_scan_id(session)
    await enqueue(
        session, seed_url, CrawlKind.FAN_COLLECTION,
        scan_id=scan_id, priority=SEED_PRIORITY,
    )
    await session.commit()
    return seed_url
