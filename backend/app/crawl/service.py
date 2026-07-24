"""Crawl operations: fetch a page, parse it, map it into the graph, and enqueue
the follow-up work it reveals.

Two operations power the whole walk:

    crawl_fan_collection → ingest a fan's owned items, enqueue each owned ALBUM
    crawl_album          → ingest album+tracks+tags+supporters, enqueue each
                           supporter's FAN_COLLECTION

Chained, they traverse the supporter→collection→album→supporter graph. The
frontier's (url, kind) uniqueness stops the walk from revisiting a node.

Operations take a `Fetcher` (satisfied by `ScraperGateway`) so they can be unit
tested against a fake that replays saved fixtures — no live credits spent.
"""

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bandcamp.collection_api import CollectionApiClient
from app.bandcamp.mapper import ingest_album, ingest_album_supporters, ingest_fan_collection
from app.bandcamp.parse import parse_album_page, parse_album_supporters, parse_fan_page
from app.crawl.frontier import enqueue
from app.db.models import Album
from app.enums import CrawlKind
from app.scraping.base import FetchRequest, FetchResult


class Fetcher(Protocol):
    async def fetch(self, request: FetchRequest) -> FetchResult: ...


@dataclass(slots=True)
class CrawlOutcome:
    url: str
    kind: str
    items: int = 0  # owned items ingested (fan collection)
    tracks: int = 0  # tracks ingested (album)
    supporters: int = 0  # supporter edges ingested (album)
    enqueued: int = 0  # new frontier rows added


def fan_collection_request(url: str) -> FetchRequest:
    """Plain render of the fan page — just enough to read the embedded blob.

    The blob carries the fan_id, the first page of owned items, and the pagination
    `last_token`. The rest of the collection is fetched by mimicking the
    `collection_items` XHR directly (see `CollectionApiClient`) rather than
    auto-scrolling the rendered page.
    """
    return FetchRequest(url=url, parser_name="fan_collection", render=True)


def album_request(url: str) -> FetchRequest:
    return FetchRequest(url=url, parser_name="album_page", render=True)


def _within_depth(depth: int, max_depth: int | None) -> bool:
    """Whether children of an entry at `depth` should be enqueued."""
    return max_depth is None or depth < max_depth


async def crawl_fan_collection(
    session: AsyncSession,
    fetcher: Fetcher,
    url: str,
    *,
    is_me: bool = False,
    collection_client: CollectionApiClient | None = None,
    depth: int = 0,
    max_depth: int | None = None,
) -> CrawlOutcome:
    """Fetch a fan page, ingest their whole collection, and enqueue each owned album.

    The rendered page gives the first page + fan_id + pagination token; the rest is
    pulled by mimicking the `collection_items` XHR (deterministic, no auto-scroll).
    Owned albums are enqueued at `depth + 1`, capped by `max_depth`.
    """
    result = await fetcher.fetch(fan_collection_request(url))
    if not result.html:
        raise ValueError(f"no HTML returned for fan page {url}")

    fc = parse_fan_page(result.html)

    # Page through the remainder of the collection via the XHR API.
    if fc.more_available and fc.last_token and fc.fan.fan_id:
        client = collection_client or CollectionApiClient()
        seen = {i.item_id for i in fc.items}
        async for item in client.iter_items(fc.fan.fan_id, fc.last_token):
            if item.item_id not in seen:
                seen.add(item.item_id)
                fc.items.append(item)

    counts = await ingest_fan_collection(session, fc, is_me=is_me)

    enqueued = 0
    if _within_depth(depth, max_depth):
        for item in fc.items:
            if item.item_type == "album" and item.url:
                if await enqueue(session, item.url, CrawlKind.ALBUM, depth=depth + 1):
                    enqueued += 1
    await session.commit()

    return CrawlOutcome(
        url=url,
        kind=str(CrawlKind.FAN_COLLECTION),
        items=counts.fan_items,
        enqueued=enqueued,
    )


async def crawl_album(
    session: AsyncSession,
    fetcher: Fetcher,
    url: str,
    *,
    depth: int = 0,
    max_depth: int | None = None,
) -> CrawlOutcome:
    """Fetch an album page, ingest album/tracks/tags/supporters, enqueue supporters.

    Supporter collections are enqueued at `depth + 1`, capped by `max_depth`.
    """
    result = await fetcher.fetch(album_request(url))
    if not result.html:
        raise ValueError(f"no HTML returned for album page {url}")

    pa = parse_album_page(result.html)
    acounts = await ingest_album(session, pa)

    album = (
        await session.execute(select(Album).where(Album.bandcamp_id == pa.album_id))
    ).scalar_one()

    sup = parse_album_supporters(result.html)
    scounts = await ingest_album_supporters(session, album, sup)

    enqueued = 0
    if _within_depth(depth, max_depth):
        for s in sup.supporters:
            if s.url and await enqueue(
                session, s.url, CrawlKind.FAN_COLLECTION, depth=depth + 1
            ):
                enqueued += 1
    await session.commit()

    return CrawlOutcome(
        url=url,
        kind=str(CrawlKind.ALBUM),
        tracks=acounts.tracks,
        supporters=scounts.supporters,
        enqueued=enqueued,
    )
