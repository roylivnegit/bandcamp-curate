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

from app.bandcamp.mapper import ingest_album, ingest_album_supporters, ingest_fan_collection
from app.bandcamp.parse import (
    parse_album_page,
    parse_album_supporters,
    parse_collection_items_capture,
    parse_fan_page,
)
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
    """Render the fan page and capture the paginated `collection_items` XHRs.

    Uses the confirmed v2 shapes: `network_capture` filters wrap under `filter`,
    and `browser_actions` key each step by its action name. Auto-scroll makes the
    deeper collection pages fire so the capture accumulates them.
    """
    return FetchRequest(
        url=url,
        parser_name="fan_collection",
        render=True,
        network_capture=[
            {"filter": {"url": {"type": "contains", "value": "collection_items"}}}
        ],
        browser_actions=[{"auto_scroll": True}, {"wait": 2000}],
    )


def album_request(url: str) -> FetchRequest:
    return FetchRequest(url=url, parser_name="album_page", render=True)


async def crawl_fan_collection(
    session: AsyncSession,
    fetcher: Fetcher,
    url: str,
    *,
    is_me: bool = False,
) -> CrawlOutcome:
    """Fetch a fan page, ingest their collection, and enqueue each owned album."""
    result = await fetcher.fetch(fan_collection_request(url))
    if not result.html:
        raise ValueError(f"no HTML returned for fan page {url}")

    fc = parse_fan_page(result.html)

    # Fold in any deeper collection pages captured from the pagination XHRs.
    if result.raw:
        captured, _token, _more = parse_collection_items_capture(result.raw)
        seen = {i.item_id for i in fc.items}
        for item in captured:
            if item.item_id not in seen:
                seen.add(item.item_id)
                fc.items.append(item)

    counts = await ingest_fan_collection(session, fc, is_me=is_me)

    enqueued = 0
    for item in fc.items:
        if item.item_type == "album" and item.url:
            if await enqueue(session, item.url, CrawlKind.ALBUM):
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
) -> CrawlOutcome:
    """Fetch an album page, ingest album/tracks/tags/supporters, enqueue supporters."""
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
    for s in sup.supporters:
        if s.url and await enqueue(session, s.url, CrawlKind.FAN_COLLECTION):
            enqueued += 1
    await session.commit()

    return CrawlOutcome(
        url=url,
        kind=str(CrawlKind.ALBUM),
        tracks=acounts.tracks,
        supporters=scounts.supporters,
        enqueued=enqueued,
    )
