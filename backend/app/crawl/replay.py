"""Re-derive a crawl's fan-out from stored rows instead of re-fetching the page.

The frontier is per-scan but the graph is global, so when a scan reaches a page
another scan already crawled there is nothing to learn from fetching it again —
the bands, albums, tracks and supporter edges are already in the database.

But "already crawled, skip it" alone would break the walk. A crawl does two
things: it *ingests* a page, and it *enqueues what that page reveals*. Skipping
the fetch skips both, so the scan would stop dead at every URL another scan had
visited, silently exploring far less than it should while looking like it worked.

So we skip only the fetch. Each function here answers "what would that crawl have
enqueued?" from the rows it already produced:

    album / track  → the supporters' fan collections
    fan collection → the owned albums and tracks

Same targets, same depth, no credit. Costs one indexed query instead of a 3-35s
render, which is also why a second scan over familiar territory is near-instant.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crawl.frontier import enqueue
from app.db.models import (
    Album,
    AlbumSupporter,
    Fan,
    FanItem,
    Track,
    TrackSupporter,
)
from app.enums import CrawlKind

logger = logging.getLogger("crate_digger.crawl")


async def _enqueue_fans(
    session: AsyncSession, fan_urls: list[str], *, scan_id: int, depth: int
) -> int:
    added = 0
    for url in fan_urls:
        if url and await enqueue(
            session, url, CrawlKind.FAN_COLLECTION, scan_id=scan_id, depth=depth
        ):
            added += 1
    return added


async def replay_album_fanout(
    session: AsyncSession, url: str, *, scan_id: int, depth: int
) -> int:
    """Enqueue the fan collections of everyone who supports this album."""
    urls = (
        await session.execute(
            select(Fan.url)
            .select_from(AlbumSupporter)
            .join(Album, Album.id == AlbumSupporter.album_id)
            .join(Fan, Fan.id == AlbumSupporter.fan_id)
            .where(Album.url == url)
        )
    ).scalars().all()
    return await _enqueue_fans(session, list(urls), scan_id=scan_id, depth=depth)


async def replay_track_fanout(
    session: AsyncSession, url: str, *, scan_id: int, depth: int
) -> int:
    """Enqueue the fan collections of everyone who supports this track."""
    urls = (
        await session.execute(
            select(Fan.url)
            .select_from(TrackSupporter)
            .join(Track, Track.id == TrackSupporter.track_id)
            .join(Fan, Fan.id == TrackSupporter.fan_id)
            .where(Track.url == url)
        )
    ).scalars().all()
    return await _enqueue_fans(session, list(urls), scan_id=scan_id, depth=depth)


async def replay_fan_collection_fanout(
    session: AsyncSession, url: str, *, scan_id: int, depth: int
) -> int:
    """Enqueue the albums and tracks this fan owns.

    Wishlist items are excluded, matching the live crawl: `crawl_fan_collection`
    only enqueues from `fc.items`. The followed-artist prune is NOT applied here —
    it keys off the crawling scan's owner, and a replay has no cheaper way to know
    it than the live path does. Worst case it enqueues a handful of entries that
    complete for free on their own replay.
    """
    rows = (
        await session.execute(
            select(Album.url, Track.url)
            .select_from(FanItem)
            .join(Fan, Fan.id == FanItem.fan_id)
            .outerjoin(Album, Album.id == FanItem.album_id)
            .outerjoin(Track, Track.id == FanItem.track_id)
            .where(Fan.url == url, FanItem.is_wishlist.is_(False))
        )
    ).all()

    from app.crawl.service import kind_for_url  # local import avoids a cycle

    added = 0
    for album_url, track_url in rows:
        target = album_url or track_url
        if not target:
            continue
        kind = kind_for_url(target)  # route on the URL, never the item type
        if kind is None:
            continue
        if await enqueue(session, target, kind, scan_id=scan_id, depth=depth):
            added += 1
    return added


async def replay_fanout(
    session: AsyncSession, url: str, kind: str, *, scan_id: int, depth: int
) -> int:
    """Enqueue whatever crawling `(url, kind)` would have revealed. → count added.

    `depth` is the depth the children get (i.e. the entry's depth + 1); the caller
    applies its own max-depth bound before calling.
    """
    if kind == CrawlKind.FAN_COLLECTION:
        return await replay_fan_collection_fanout(session, url, scan_id=scan_id, depth=depth)
    if kind == CrawlKind.ALBUM:
        return await replay_album_fanout(session, url, scan_id=scan_id, depth=depth)
    if kind == CrawlKind.TRACK:
        return await replay_track_fanout(session, url, scan_id=scan_id, depth=depth)
    logger.warning("no replay for crawl kind %s (%s)", kind, url)
    return 0
