"""Crawl operations: fetch a page, parse it, map it into the graph, and enqueue
the follow-up work it reveals.

Three operations power the whole walk:

    crawl_fan_collection → ingest a fan's owned items, enqueue each owned ALBUM
                           and each owned standalone TRACK
    crawl_album          → ingest album+tracks+tags+supporters, enqueue each
                           supporter's FAN_COLLECTION
    crawl_track          → same for a standalone track page

Chained, they traverse the supporter→collection→album/track→supporter graph. The
frontier's (url, kind) uniqueness stops the walk from revisiting a node, and past
`FOLLOWED_FILTER_MIN_DEPTH` a neighbour's items by artists the seed fan already
follows are ingested but not detail-crawled (see `crawl_fan_collection`).

Operations take a `Fetcher` (satisfied by `ScraperGateway`) so they can be unit
tested against a fake that replays saved fixtures — no live credits spent.
"""

import logging
import re
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bandcamp.collection_api import WISHLIST_ITEMS_URL, CollectionApiClient
from app.bandcamp.follows_api import FollowsApiClient
from app.bandcamp.mapper import (
    get_or_create_fan,
    ingest_album,
    ingest_album_supporters,
    ingest_follows_batch,
    ingest_items_batch,
    ingest_track_page,
    ingest_track_supporters,
)
from app.bandcamp.parse import (
    ParsedItem,
    parse_album_page,
    parse_album_supporters,
    parse_fan_page,
    parse_track_page,
)
from app.bandcamp.supporters_api import SupportersApiClient
from app.bandcamp.urls import url_host
from app.crawl.frontier import enqueue
from app.db.models import Album, Band, CrawlFrontier, Fan, Follow, Track
from app.enums import CrawlKind
from app.scraping.base import FetchRequest, FetchResult

logger = logging.getLogger("crate_digger.crawl")

# From this depth down, a neighbour's owned item whose artist/label the seed fan
# already follows is ingested but NOT enqueued for a detail crawl. Its ownership
# edge is what feeds co-ownership scoring; its page (tags, supporters, subgraph)
# only feeds recommendations curation would exclude anyway, so the render is
# wasted credits. 2 = "the collections of my albums' supporters" — everything
# shallower (my own collection at 0, its albums at 1) is always crawled in full.
FOLLOWED_FILTER_MIN_DEPTH = 2

# Pagination requests one visit to a fan collection may spend before it parks
# itself and lets the rest of the frontier have a turn. Collections are big
# (p90 ≈ 1,700 items ≈ 43 pages), and paging one to the end in a single job is
# what blew past ARQ's `job_timeout` and threw the whole collection away. A
# bounded slice per visit keeps every job short, and the leftover tokens
# (`CrawlOutcome.cursor` → `crawl_frontier.cursor`) resume the rest next pass.
PAGES_PER_VISIT = 10

# The three independently-paginated lists behind one fan page. Only `collection`
# is paged for other people; the wishlist and follows lists matter for your own
# account, where they gate curation's exclusions.
_CURSOR_STREAMS = ("collection", "wishlist", "follows")


class Fetcher(Protocol):
    async def fetch(self, request: FetchRequest) -> FetchResult: ...


def build_pagination_clients(
    gateway: Fetcher, *, via_nimble: bool
) -> tuple[CollectionApiClient, FollowsApiClient, SupportersApiClient]:
    """The three pagination clients, routed through Nimble (via the gateway) or
    direct-to-Bandcamp per `via_nimble`. Used by the worker and the CLI."""
    gw = gateway if via_nimble else None
    return (
        CollectionApiClient(gateway=gw),
        FollowsApiClient(gateway=gw),
        SupportersApiClient(gateway=gw),
    )


@dataclass(slots=True)
class CrawlOutcome:
    url: str
    kind: str
    items: int = 0  # owned items ingested (fan collection)
    tracks: int = 0  # tracks ingested (album)
    supporters: int = 0  # supporter edges ingested (album)
    enqueued: int = 0  # new frontier rows added
    skipped_followed: int = 0  # owned items not enqueued — band already followed
    fan_id: int | None = None  # the ingested Fan's id (fan collection only)
    # Left-over pagination tokens when a fan collection outran its page budget.
    # None = fully paged. The runner parks a cursored entry back as PENDING.
    cursor: dict | None = None


@dataclass(slots=True, frozen=True)
class FollowedBands:
    """The artists/labels one fan follows, keyed the two ways a release can point
    back at them: the Bandcamp band id it's stored under, and the storefront host
    it lives on.

    Both are needed because a followed *label* usually isn't the band a release is
    stored under — label releases carry the **artist's** band_id but sit on the
    label's subdomain. This mirrors `curation.build_exclusions` exactly, so an item
    this matches is one curation would drop from the feed regardless.
    """

    band_ids: frozenset[int]
    hosts: frozenset[str]

    def __bool__(self) -> bool:
        return bool(self.band_ids or self.hosts)

    def covers(self, item: ParsedItem) -> bool:
        """Whether `item` belongs to a followed artist/label."""
        return item.band.bandcamp_id in self.band_ids or url_host(item.url) in self.hosts


EMPTY_FOLLOWS = FollowedBands(band_ids=frozenset(), hosts=frozenset())


async def followed_bands(session: AsyncSession, fan_id: int) -> FollowedBands:
    """Load every band `fan_id` follows, as ids + storefront hosts. One query per
    fan collection — the result is reused for that whole collection's items."""
    rows = (
        await session.execute(
            select(Band.bandcamp_id, Band.url)
            .join(Follow, Follow.band_id == Band.id)
            .where(Follow.fan_id == fan_id)
        )
    ).all()
    return FollowedBands(
        band_ids=frozenset(bid for bid, _ in rows if bid is not None),
        hosts=frozenset(h for h in (url_host(u) for _, u in rows) if h),
    )


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


def track_request(url: str) -> FetchRequest:
    return FetchRequest(url=url, parser_name="track_page", render=True)


def _within_depth(depth: int, max_depth: int | None) -> bool:
    """Whether children of an entry at `depth` should be enqueued."""
    return max_depth is None or depth < max_depth


# A Bandcamp release URL: /album/<slug> or /track/<slug> on any host.
_ITEM_PATH_RE = re.compile(r"^https?://[^/]+/(album|track)/", re.IGNORECASE)
_URL_KIND = {"album": CrawlKind.ALBUM, "track": CrawlKind.TRACK}


def kind_for_url(url: str) -> CrawlKind | None:
    """The crawl kind a URL's own path implies — None if it's neither.

    Route the frontier on this, never on a collection item's `item_type`. The two
    disagree routinely, and only the URL can be trusted here: `item_type` describes
    the *item you own*, while the frontier's kind picks the *parser*, and each
    parser reads the release id straight off the page it's given.

    `parse_collection_item` labels anything Bandcamp doesn't call an "album" a
    track — which sweeps in `package` items (vinyl/CD), whose URL is the /album/
    page. Handing that to `parse_track_page` doesn't fail; it reads the album's
    tralbum id and writes a phantom Track under it, carrying the album's supporters
    as TrackSupporters. Curation then scores that ghost against the real album, and
    one-per-band dedup can let it win. It also defeats the frontier's (url, kind)
    dedup, so the page is rendered twice.
    """
    m = _ITEM_PATH_RE.match(url)
    return _URL_KIND[m.group(1).lower()] if m else None


async def _enqueue_items(
    session: AsyncSession,
    items: list[ParsedItem],
    *,
    depth: int,
    max_depth: int | None,
    followed: FollowedBands,
) -> tuple[int, int]:
    """Enqueue one page of owned items as ALBUM/TRACK crawls → (enqueued, skipped).

    Kind comes from the URL (`kind_for_url`), never `item_type`. Items by an
    artist/label the seed fan already follows are counted as skipped, not queued.
    """
    if not _within_depth(depth, max_depth):
        return 0, 0
    enqueued = skipped = 0
    for item in items:
        if not item.url:
            continue
        kind = kind_for_url(item.url)
        if kind is None:  # not a release page — don't guess a parser for it
            logger.debug("not enqueuing %s: neither an album nor a track URL", item.url)
            continue
        if followed and followed.covers(item):
            skipped += 1
            continue
        if await enqueue(session, item.url, kind, depth=depth + 1):
            enqueued += 1
    return enqueued, skipped


def _next_token(current: str | None, nxt: str | None, more: bool) -> str | None:
    """The token to page from next, or None when this stream is exhausted.
    Guards against a provider echoing the same token back forever."""
    return nxt if (more and nxt and nxt != current) else None


async def crawl_fan_collection(
    session: AsyncSession,
    fetcher: Fetcher,
    url: str,
    *,
    is_me: bool = False,
    collection_client: CollectionApiClient | None = None,
    follows_client: FollowsApiClient | None = None,
    depth: int = 0,
    max_depth: int | None = None,
    seed_fan_id: int | None = None,
    cursor: dict | None = None,
    pages_per_visit: int = PAGES_PER_VISIT,
    entry: CrawlFrontier | None = None,
) -> CrawlOutcome:
    """Ingest a bounded slice of a fan's collection and enqueue what it reveals.

    A visit spends at most `pages_per_visit` pagination requests and **commits
    after every page**, so the work already done survives a timeout, a restart,
    or a crash. If the collection outruns the budget, the leftover tokens come
    back as `outcome.cursor`; the runner parks the entry as PENDING carrying
    them, and a later pass resumes from exactly there (see `frontier.mark_partial`).
    Collections are large — p90 in our data is ~1,700 items ≈ 43 pages — so this
    is the normal path, not an edge case.

    First visit (`cursor is None`) renders the fan page: that's where the fan_id,
    the embedded first page, and the initial tokens live. **Resuming skips the
    render entirely** — the tokens carry everything needed, so a resumed visit
    costs only its pagination.

    Owned items are enqueued at `depth + 1` (capped by `max_depth`) as ALBUM or
    TRACK per `kind_for_url` — the item's *URL*, not its `item_type`, which lies
    often enough to corrupt data. For your own account (`is_me`) the wishlist and
    follows lists are paged too, from the same budget, since both gate curation.

    `seed_fan_id` is the fan the walk is *for* (the scan owner's own Fan). From
    `FOLLOWED_FILTER_MIN_DEPTH` down, items by an artist/label that fan already
    follows are still ingested — the ownership edge is the co-ownership signal —
    but are not enqueued for a detail crawl, since curation excludes them anyway.
    Passing None (the legacy operator crawl) disables the filter.

    Pass the frontier `entry` to have the bookmark **checkpointed into each page's
    commit**, so a crash leaves the position as durable as the data. Without it the
    cursor is only returned at the end, and an interruption re-buys the whole
    visit's pages on the next run.
    """
    col_client = collection_client or CollectionApiClient()
    fol_client = follows_client or FollowsApiClient()

    followed = EMPTY_FOLLOWS
    if depth >= FOLLOWED_FILTER_MIN_DEPTH and seed_fan_id is not None:
        followed = await followed_bands(session, seed_fan_id)

    ingested = enqueued = skipped = 0
    fan: Fan
    bc_fan_id: int
    tokens: dict[str, str | None]

    def snapshot() -> dict | None:
        """The resume bookmark for the tokens as they stand, or None if exhausted."""
        return {"fan_id": bc_fan_id, **tokens} if any(tokens.values()) else None

    async def checkpoint() -> None:
        """Commit the page's work AND its bookmark together, so an interruption
        can never leave ingested pages the next run doesn't know it already has."""
        if entry is not None:
            entry.cursor = snapshot()
        await session.commit()

    async def absorb(batch: list[ParsedItem], *, is_wishlist: bool = False) -> None:
        """Ingest a page, queue what it reveals, checkpoint — one durable unit.
        Callers must advance `tokens` BEFORE calling, so the bookmark committed
        here means "everything up to and including this page is ingested"."""
        nonlocal ingested, enqueued, skipped
        ingested += await ingest_items_batch(session, fan, batch, is_wishlist=is_wishlist)
        if not is_wishlist:
            e, s = await _enqueue_items(
                session, batch, depth=depth, max_depth=max_depth, followed=followed
            )
            enqueued += e
            skipped += s
        await checkpoint()

    if cursor:
        # Resuming: no render needed, the cursor holds the fan and the tokens.
        bc_fan_id = cursor["fan_id"]
        found = (
            await session.execute(select(Fan).where(Fan.bandcamp_fan_id == bc_fan_id))
        ).scalar_one_or_none()
        if found is None:
            raise ValueError(f"cannot resume {url}: fan {bc_fan_id} was never ingested")
        fan = found
        tokens = {k: cursor.get(k) for k in _CURSOR_STREAMS}
    else:
        result = await fetcher.fetch(fan_collection_request(url))
        if not result.html:
            raise ValueError(f"no HTML returned for fan page {url}")
        fc = parse_fan_page(result.html)
        bc_fan_id = fc.fan.fan_id
        fan = await get_or_create_fan(
            session, fc.fan.fan_id, fc.fan.username,
            name=fc.fan.name, url=fc.fan.url, is_me=is_me,
        )
        # Tokens first: `absorb` checkpoints them, so they must already describe
        # what remains AFTER the embedded page it's about to ingest.
        tokens = {
            "collection": _next_token(None, fc.last_token, fc.more_available),
            "wishlist": _next_token(None, fc.wishlist_last_token, fc.wishlist_more_available)
            if is_me else None,
            "follows": _next_token(None, fc.follows_last_token, fc.follows_more_available)
            if is_me else None,
        }
        # The page embeds the first page of each list — free with the render.
        await absorb(fc.items)
        if is_me:
            await absorb(fc.wishlist, is_wishlist=True)
            await ingest_follows_batch(session, fan, fc.follows)
            await checkpoint()

    # Spend the visit's page budget: collection first, then (is_me only) the
    # wishlist and follows lists that gate curation.
    pages_left = pages_per_visit
    while pages_left > 0 and tokens["collection"]:
        batch, nxt, more = await col_client.fetch_page(bc_fan_id, tokens["collection"])
        pages_left -= 1
        tokens["collection"] = _next_token(tokens["collection"], nxt, more)
        await absorb(batch)

    while is_me and pages_left > 0 and tokens["wishlist"]:
        batch, nxt, more = await col_client.fetch_page(
            bc_fan_id, tokens["wishlist"], url=WISHLIST_ITEMS_URL
        )
        pages_left -= 1
        tokens["wishlist"] = _next_token(tokens["wishlist"], nxt, more)
        await absorb(batch, is_wishlist=True)

    while is_me and pages_left > 0 and tokens["follows"]:
        bands, nxt, more = await fol_client.fetch_page(bc_fan_id, tokens["follows"])
        pages_left -= 1
        tokens["follows"] = _next_token(tokens["follows"], nxt, more)
        await ingest_follows_batch(session, fan, bands)
        await checkpoint()

    leftover = snapshot()
    if leftover is not None:
        logger.info(
            "%s paged out at %d pages; resuming later from %s",
            url, pages_per_visit, {k: bool(v) for k, v in tokens.items()},
        )

    return CrawlOutcome(
        url=url,
        kind=str(CrawlKind.FAN_COLLECTION),
        items=ingested,
        enqueued=enqueued,
        skipped_followed=skipped,
        fan_id=fan.id,
        cursor=leftover,
    )


async def crawl_album(
    session: AsyncSession,
    fetcher: Fetcher,
    url: str,
    *,
    depth: int = 0,
    max_depth: int | None = None,
    supporters_client: SupportersApiClient | None = None,
) -> CrawlOutcome:
    """Fetch an album page, ingest album/tracks/tags/supporters, enqueue supporters.

    The page embeds the first page of supporters; the rest are pulled by mimicking
    the collectors `thumbs` XHR. Supporter collections are enqueued at `depth + 1`,
    capped by `max_depth`.
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

    # Page through the remaining supporters via the thumbs XHR.
    if sup.more_available and sup.last_token and sup.album_id:
        client = supporters_client or SupportersApiClient()
        seen = {s.username for s in sup.supporters}
        async for s in client.iter_supporters(
            sup.album_id, sup.last_token, tralbum_type=sup.tralbum_type
        ):
            if s.username not in seen:
                seen.add(s.username)
                sup.supporters.append(s)

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


async def crawl_track(
    session: AsyncSession,
    fetcher: Fetcher,
    url: str,
    *,
    depth: int = 0,
    max_depth: int | None = None,
    supporters_client: SupportersApiClient | None = None,
) -> CrawlOutcome:
    """Fetch a standalone track page, ingest track/band/tags/supporters, enqueue
    supporters. Mirrors `crawl_album` but scoped to one track — its own supporters
    (people who bought/wishlisted that specific track), not the parent album's; the
    parent album (if any) is only stubbed, not itself crawled.
    """
    result = await fetcher.fetch(track_request(url))
    if not result.html:
        raise ValueError(f"no HTML returned for track page {url}")

    pt = parse_track_page(result.html)
    await ingest_track_page(session, pt)

    track = (
        await session.execute(select(Track).where(Track.bandcamp_id == pt.track_id))
    ).scalar_one()

    sup = parse_album_supporters(result.html)  # tralbum-generic; album_id here is the track's id

    # Page through the remaining supporters via the thumbs XHR.
    if sup.more_available and sup.last_token and sup.album_id:
        client = supporters_client or SupportersApiClient()
        seen = {s.username for s in sup.supporters}
        async for s in client.iter_supporters(
            sup.album_id, sup.last_token, tralbum_type=sup.tralbum_type
        ):
            if s.username not in seen:
                seen.add(s.username)
                sup.supporters.append(s)

    scounts = await ingest_track_supporters(session, track, sup)

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
        kind=str(CrawlKind.TRACK),
        supporters=scounts.supporters,
        enqueued=enqueued,
    )
