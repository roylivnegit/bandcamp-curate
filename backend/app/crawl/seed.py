"""Seed the crawl from your own Bandcamp fan page (`BANDCAMP_FAN_URL`).

The seed is a high-priority FAN_COLLECTION so it drains first; the runner marks it
`is_me` by matching the URL, which is what records your follows (see
`ingest_fan_collection`). Everything else is discovered from there.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.crawl.frontier import enqueue
from app.enums import CrawlKind

SEED_PRIORITY = 100


async def seed_fan_collection(
    session: AsyncSession, url: str | None = None, *, settings: Settings | None = None
) -> str:
    """Enqueue the seed fan collection. Returns the seeded URL."""
    settings = settings or get_settings()
    seed_url = url or settings.bandcamp_fan_url
    if not seed_url:
        raise ValueError("no seed URL: set BANDCAMP_FAN_URL or pass url=")
    await enqueue(session, seed_url, CrawlKind.FAN_COLLECTION, priority=SEED_PRIORITY)
    await session.commit()
    return seed_url
