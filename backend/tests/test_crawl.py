from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.bandcamp.collection_api import (
    COLLECTION_ITEMS_URL,
    WISHLIST_ITEMS_URL,
    CollectionApiClient,
)
from app.bandcamp.follows_api import FollowsApiClient
from app.bandcamp.parse import ParsedBand, ParsedItem, ParsedSupporter
from app.bandcamp.supporters_api import SupportersApiClient
from app.crawl import frontier, runner
from app.crawl.seed import seed_fan_collection
from app.crawl.service import (
    FOLLOWED_FILTER_MIN_DEPTH,
    crawl_album,
    crawl_fan_collection,
    crawl_track,
    followed_bands,
)
from app.db.base import Base
from app.db.models import (
    Album,
    AlbumSupporter,
    Band,
    CrawlFrontier,
    Fan,
    FanItem,
    Follow,
    ProviderUsage,
    Track,
    TrackSupporter,
)
from app.enums import CrawlKind, CrawlStatus, TargetType
from app.scraping.base import FetchRequest, FetchResult

FIXTURES = Path(__file__).parent / "fixtures"
FAN_HTML = (FIXTURES / "fan_page.html").read_text()
ALBUM_HTML = (FIXTURES / "album_page.html").read_text()
TRACK_HTML = (FIXTURES / "track_page.html").read_text()
ALBUM_URL = "https://cerebro-spinal.bandcamp.com/album/panchito"
TRACK_URL = "https://jscottg.bandcamp.com/track/return-of-the-king-original-mix"
SEED_URL = "https://bandcamp.com/guron"
ME_URL = "https://bandcamp.com/me"  # the seed fan in the followed-filter tests


class FakeFetcher:
    """Replays saved HTML by URL substring — no network, no credits."""

    def __init__(self, routes: dict[str, str]) -> None:
        self.routes = routes
        self.calls: list[str] = []

    async def fetch(self, request: FetchRequest) -> FetchResult:
        self.calls.append(request.url)
        for needle, html in self.routes.items():
            if needle in request.url:
                return FetchResult(
                    url=request.url, provider="fake", status_code=200, ok=True, html=html
                )
        raise AssertionError(f"no fake route for {request.url}")


class FakeCollectionClient:
    """Stands in for the collection_items / wishlist_items XHRs (URL-routed)."""

    def __init__(
        self, items: list[ParsedItem] | None = None,
        wishlist: list[ParsedItem] | None = None,
    ) -> None:
        self._items = items or []
        self._wishlist = wishlist or []

    async def iter_items(
        self, fan_id: int, start_token: str, *,
        url: str = COLLECTION_ITEMS_URL, max_pages: int = 100,
    ) -> AsyncIterator[ParsedItem]:
        for item in (self._wishlist if url == WISHLIST_ITEMS_URL else self._items):
            yield item


def _album_item(item_id: int, url: str) -> ParsedItem:
    return ParsedItem(
        item_id=item_id, item_type="album",
        band=ParsedBand(bandcamp_id=item_id + 1, name="Paged Band"),
        title="Paged Album", url=url,
    )


class FakeSupportersClient:
    """Stands in for the collectors thumbs XHR — yields preset extra supporters."""

    def __init__(self, supporters: list[ParsedSupporter] | None = None) -> None:
        self._supporters = supporters or []

    async def iter_supporters(
        self, tralbum_id: int, start_token: str, *, tralbum_type: str = "a",
        max_pages: int = 100,
    ) -> AsyncIterator[ParsedSupporter]:
        for s in self._supporters:
            yield s


def _supporter(username: str) -> ParsedSupporter:
    return ParsedSupporter(username=username, url=f"https://bandcamp.com/{username}")


@pytest_asyncio.fixture
async def sessionmaker_() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest_asyncio.fixture
async def session(
    sessionmaker_: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with sessionmaker_() as s:
        yield s


async def _count(session: AsyncSession, model) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


# ── Frontier ──────────────────────────────────────────────────────────────────


async def test_enqueue_is_idempotent(session: AsyncSession) -> None:
    assert await frontier.enqueue(session, SEED_URL, CrawlKind.FAN_COLLECTION) is True
    assert await frontier.enqueue(session, SEED_URL, CrawlKind.FAN_COLLECTION) is False
    await session.commit()
    assert await _count(session, CrawlFrontier) == 1


async def test_claim_next_orders_by_priority(session: AsyncSession) -> None:
    await frontier.enqueue(session, "https://a", CrawlKind.ALBUM, priority=0)
    await frontier.enqueue(session, "https://b", CrawlKind.FAN_COLLECTION, priority=100)
    await session.commit()

    entry = await frontier.claim_next(session)
    assert entry is not None and entry.url == "https://b"  # higher priority first
    assert entry.status == CrawlStatus.IN_PROGRESS
    assert entry.attempts == 1


async def test_claim_next_returns_none_when_empty(session: AsyncSession) -> None:
    assert await frontier.claim_next(session) is None


# ── Crawl operations ────────────────────────────────────────────────────────────


async def test_crawl_fan_collection_ingests_and_enqueues_albums(
    session: AsyncSession,
) -> None:
    fetcher = FakeFetcher({"bandcamp.com/guron": FAN_HTML})
    # The XHR pagination yields one more owned album beyond the embedded first page.
    paged = _album_item(555001, "https://paged.bandcamp.com/album/extra")
    client = FakeCollectionClient([paged])
    outcome = await crawl_fan_collection(
        session, fetcher, SEED_URL, is_me=True, collection_client=client
    )

    assert outcome.items == 3  # 2 embedded (album+track) + 1 paged album
    assert await _count(session, FanItem) == 3
    # Both owned albums (embedded + paged) should now be queued as ALBUM crawls.
    albums = (
        await session.execute(
            select(CrawlFrontier).where(CrawlFrontier.kind == CrawlKind.ALBUM)
        )
    ).scalars().all()
    assert len(albums) == 2
    assert "https://paged.bandcamp.com/album/extra" in {a.url for a in albums}
    # …and the owned standalone track as a TRACK crawl (its own supporters differ
    # from the parent album's, so it's a distinct node in the graph).
    tracks = (
        await session.execute(
            select(CrawlFrontier).where(CrawlFrontier.kind == CrawlKind.TRACK)
        )
    ).scalars().all()
    assert [t.url for t in tracks] == [TRACK_URL]
    assert outcome.enqueued == len(albums) + len(tracks) == 3


async def test_crawl_fan_collection_propagates_depth_to_owned_items(
    session: AsyncSession,
) -> None:
    fetcher = FakeFetcher({"bandcamp.com/guron": FAN_HTML})
    await crawl_fan_collection(
        session, fetcher, SEED_URL, is_me=True,
        collection_client=FakeCollectionClient(), depth=1, max_depth=3,
    )
    entries = (await session.execute(select(CrawlFrontier))).scalars().all()
    assert {e.kind for e in entries} == {CrawlKind.ALBUM, CrawlKind.TRACK}
    assert all(e.depth == 2 for e in entries)  # children at depth+1


async def test_crawl_fan_collection_at_max_depth_enqueues_nothing(
    session: AsyncSession,
) -> None:
    # Items are still ingested at the boundary; only outward enqueue stops — and
    # that applies to owned tracks exactly as it does to owned albums.
    fetcher = FakeFetcher({"bandcamp.com/guron": FAN_HTML})
    outcome = await crawl_fan_collection(
        session, fetcher, SEED_URL, is_me=True,
        collection_client=FakeCollectionClient(), depth=3, max_depth=3,
    )
    assert outcome.items == 2 and outcome.enqueued == 0
    assert await _count(session, CrawlFrontier) == 0


# ── Followed-artist pruning (depth ≥ FOLLOWED_FILTER_MIN_DEPTH) ────────────────


async def _seed_fan_following(
    session: AsyncSession, *, band_bandcamp_id: int, band_url: str | None
) -> int:
    """A Fan with one Follow row, and the followed Band. Returns the fan's id."""
    fan = Fan(bandcamp_fan_id=1, username="me", url=ME_URL)
    band = Band(bandcamp_id=band_bandcamp_id, name="Followed", url=band_url)
    session.add_all([fan, band])
    await session.flush()
    session.add(Follow(fan_id=fan.id, band_id=band.id, target_type=str(TargetType.ARTIST)))
    await session.commit()
    return fan.id


async def _frontier_urls(session: AsyncSession) -> set[str]:
    return {
        e.url for e in (await session.execute(select(CrawlFrontier))).scalars().all()
    }


async def test_followed_band_is_ingested_but_not_detail_crawled(
    session: AsyncSession,
) -> None:
    # A neighbour (depth 2) owns an album by a band I already follow. Curation would
    # exclude it, so we skip the page render — but the ownership edge still lands.
    fan_id = await _seed_fan_following(
        session, band_bandcamp_id=555002, band_url="https://followed.bandcamp.com"
    )
    fetcher = FakeFetcher({"bandcamp.com/guron": FAN_HTML})
    followed_item = _album_item(555001, "https://paged.bandcamp.com/album/extra")
    assert followed_item.band.bandcamp_id == 555002  # _album_item's band id = id + 1

    outcome = await crawl_fan_collection(
        session, fetcher, SEED_URL,
        collection_client=FakeCollectionClient([followed_item]),
        depth=2, max_depth=4, seed_fan_id=fan_id,
    )

    assert outcome.items == 3  # still ingested — co-ownership needs the edge
    assert await _count(session, FanItem) == 3
    assert outcome.skipped_followed == 1
    assert "https://paged.bandcamp.com/album/extra" not in await _frontier_urls(session)
    # The unfollowed items in the same collection are enqueued as usual.
    assert outcome.enqueued == 2
    assert {ALBUM_URL, TRACK_URL} == await _frontier_urls(session)


async def test_followed_label_matched_by_url_host(session: AsyncSession) -> None:
    # A followed *label*: its releases are stored under the artist's band_id, so only
    # the storefront host identifies them — the same match curation makes.
    fan_id = await _seed_fan_following(
        session, band_bandcamp_id=999999, band_url="https://paged.bandcamp.com"
    )
    fetcher = FakeFetcher({"bandcamp.com/guron": FAN_HTML})
    label_release = _album_item(555001, "https://paged.bandcamp.com/album/extra")

    outcome = await crawl_fan_collection(
        session, fetcher, SEED_URL,
        collection_client=FakeCollectionClient([label_release]),
        depth=2, max_depth=4, seed_fan_id=fan_id,
    )

    assert outcome.skipped_followed == 1
    assert "https://paged.bandcamp.com/album/extra" not in await _frontier_urls(session)


async def test_followed_filter_is_off_above_min_depth(session: AsyncSession) -> None:
    # My own collection (0) and its albums (1) are always crawled in full — a band
    # I follow *and* own is exactly the taste signal the walk starts from.
    fan_id = await _seed_fan_following(
        session, band_bandcamp_id=555002, band_url="https://paged.bandcamp.com"
    )
    fetcher = FakeFetcher({"bandcamp.com/guron": FAN_HTML})
    followed_item = _album_item(555001, "https://paged.bandcamp.com/album/extra")

    outcome = await crawl_fan_collection(
        session, fetcher, SEED_URL, is_me=True,
        collection_client=FakeCollectionClient([followed_item]),
        follows_client=FakeFollowsClient(),
        depth=FOLLOWED_FILTER_MIN_DEPTH - 1, max_depth=4, seed_fan_id=fan_id,
    )

    assert outcome.skipped_followed == 0
    assert "https://paged.bandcamp.com/album/extra" in await _frontier_urls(session)


async def test_followed_filter_needs_a_seed_fan(session: AsyncSession) -> None:
    # No seed fan (the legacy operator crawl) → nothing is pruned, even at depth.
    await _seed_fan_following(
        session, band_bandcamp_id=555002, band_url="https://paged.bandcamp.com"
    )
    fetcher = FakeFetcher({"bandcamp.com/guron": FAN_HTML})
    outcome = await crawl_fan_collection(
        session, fetcher, SEED_URL,
        collection_client=FakeCollectionClient(
            [_album_item(555001, "https://paged.bandcamp.com/album/extra")]
        ),
        depth=2, max_depth=4, seed_fan_id=None,
    )
    assert outcome.skipped_followed == 0 and outcome.enqueued == 3


async def test_followed_bands_loads_ids_and_hosts(session: AsyncSession) -> None:
    fan_id = await _seed_fan_following(
        session, band_bandcamp_id=42, band_url="https://Atomesmusic.bandcamp.com/album/x"
    )
    followed = await followed_bands(session, fan_id)
    assert followed.band_ids == frozenset({42})
    assert followed.hosts == frozenset({"atomesmusic.bandcamp.com"})  # lowercased
    assert bool(followed) is True
    # A different fan's follows are not visible — Follow rows are per-fan.
    other = Fan(bandcamp_fan_id=2, username="other", url="https://bandcamp.com/other")
    session.add(other)
    await session.commit()
    assert bool(await followed_bands(session, other.id)) is False


async def test_followed_bands_tolerates_bands_without_ids_or_urls(
    session: AsyncSession,
) -> None:
    # bands.url is nullable (discover-by-id, enrich later) — a band with neither key
    # contributes nothing rather than matching everything.
    fan = Fan(bandcamp_fan_id=1, username="me", url=ME_URL)
    band = Band(bandcamp_id=None, name="Stub", url=None)
    session.add_all([fan, band])
    await session.flush()
    session.add(Follow(fan_id=fan.id, band_id=band.id, target_type=str(TargetType.ARTIST)))
    await session.commit()

    followed = await followed_bands(session, fan.id)
    assert bool(followed) is False
    assert followed.covers(_album_item(1, "https://anything.bandcamp.com/album/x")) is False


class FakeGateway:
    """Captures FetchRequests and returns a canned JSON body as FetchResult.html."""

    def __init__(self, body: dict) -> None:
        self.requests: list[FetchRequest] = []
        self._body = body

    async def fetch(self, request: FetchRequest) -> FetchResult:
        import json as _json
        self.requests.append(request)
        return FetchResult(
            url=request.url, provider="nimble", status_code=200, ok=True,
            html=_json.dumps(self._body),
        )


async def test_collection_client_routes_through_gateway() -> None:
    gw = FakeGateway({
        "items": [{"item_id": 1, "item_type": "album", "band_id": 10,
                   "item_title": "A", "item_url": "https://a/album/a"}],
        "last_token": "t1", "more_available": False,
    })
    client = CollectionApiClient(gateway=gw)
    items, tok, more = await client.fetch_page(9985893, "t0")
    assert [i.item_id for i in items] == [1] and tok == "t1"

    import json as _json
    req = gw.requests[0]
    assert req.render is False and req.extra["method"] == "POST"
    assert req.url.endswith("/collection_items")
    body = _json.loads(req.extra["body"])
    assert body["fan_id"] == 9985893 and body["older_than_token"] == "t0"


def test_cache_key_is_body_aware() -> None:
    # POST pagination shares one URL; different bodies must not collide in the cache.
    url = "https://bandcamp.com/api/fancollection/1/collection_items"
    a = FetchRequest(url=url, parser_name="bc_api", extra={"body": '{"fan_id":1}'})
    b = FetchRequest(url=url, parser_name="bc_api", extra={"body": '{"fan_id":2}'})
    plain = FetchRequest(url=url, parser_name="bc_api")
    assert a.cache_key() != b.cache_key()
    assert plain.cache_key() == f"bc_api::{url}"


async def test_collection_api_client_paginates_and_stops() -> None:
    # Two pages of the collection_items XHR; the client should follow last_token
    # until more_available is false, and send the right POST body each time.
    seen_bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        body = _json.loads(request.content)
        seen_bodies.append(body)
        if body["older_than_token"] == "tok0":
            return httpx.Response(200, json={
                "items": [{"item_id": 1, "item_type": "album", "band_id": 10,
                           "item_title": "A", "item_url": "https://a/album/a"}],
                "last_token": "tok1", "more_available": True,
            })
        return httpx.Response(200, json={
            "items": [{"item_id": 2, "item_type": "album", "band_id": 20,
                       "item_title": "B", "item_url": "https://b/album/b"}],
            "last_token": "tok2", "more_available": False,
        })

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = CollectionApiClient(http, count=40, delay=0)
        items = [i async for i in client.iter_items(9985893, "tok0")]

    assert [i.item_id for i in items] == [1, 2]
    assert [b["older_than_token"] for b in seen_bodies] == ["tok0", "tok1"]
    assert all(b["fan_id"] == 9985893 and b["count"] == 40 for b in seen_bodies)


async def test_follows_api_client_paginates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json
        tok = _json.loads(request.content)["older_than_token"]
        if tok == "f0":
            return httpx.Response(200, json={
                "followeers": [{"band_id": 10, "name": "L1",
                                "url_hints": {"subdomain": "l1"}, "token": "f1"}],
                "more_available": True, "last_token": "f1"})
        return httpx.Response(200, json={
            "followeers": [{"band_id": 20, "name": "L2",
                            "url_hints": {"subdomain": "l2"}, "token": "f2"}],
            "more_available": False, "last_token": "f2"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        bands = [b async for b in FollowsApiClient(http, delay=0).iter_bands(9985893, "f0")]
    assert [b.bandcamp_id for b in bands] == [10, 20]
    assert bands[0].url == "https://l1.bandcamp.com"


class FakeFollowsClient:
    def __init__(self, bands: list[ParsedBand] | None = None) -> None:
        self._bands = bands or []

    async def iter_bands(
        self, fan_id: int, start_token: str, *, max_pages: int = 200
    ) -> AsyncIterator[ParsedBand]:
        for b in self._bands:
            yield b


def _fan_html_with_follows_token() -> str:
    import html as _html
    import json as _json

    blob = {
        "fan_data": {"fan_id": 9985893, "username": "guron",
                     "trackpipe_url": "https://bandcamp.com/guron"},
        "item_cache": {
            "collection": {},
            "wishlist": {},
            "following_bands": {
                "1": {"band_id": 111, "name": "Embedded One",
                      "url_hints": {"subdomain": "one"}},
                "2": {"band_id": 222, "name": "Embedded Two",
                      "url_hints": {"subdomain": "two"}},
            },
        },
        "collection_data": {"item_count": 0, "last_token": None},
        "wishlist_data": {"last_token": None},
        "following_bands_data": {"item_count": 3, "last_token": "1779:222"},
    }
    enc = _html.escape(_json.dumps(blob), quote=True)
    return f'<div id="pagedata" data-blob="{enc}"></div>'


async def test_crawl_fan_collection_pages_all_follows(session: AsyncSession) -> None:
    # 2 follows embedded + a follows token; the follows XHR adds a 3rd. is_me → all
    # become Follow rows (this is the fix for missing label-follows in curation).
    from app.db.models import Follow

    fetcher = FakeFetcher({"bandcamp.com/guron": _fan_html_with_follows_token()})
    extra = ParsedBand(bandcamp_id=987654, name="Paged Label",
                       url="https://pagedlabel.bandcamp.com")
    await crawl_fan_collection(
        session, fetcher, SEED_URL, is_me=True,
        collection_client=FakeCollectionClient(),
        follows_client=FakeFollowsClient([extra]),
    )
    n = (await session.execute(select(func.count()).select_from(Follow))).scalar_one()
    assert n == 3  # 2 embedded + 1 paged


def _fan_html_with_wishlist_token() -> str:
    import html as _html
    import json as _json

    def item(iid):
        return {"item_id": iid, "item_type": "album", "band_id": iid * 10,
                "band_name": f"B{iid}", "item_title": f"W{iid}",
                "item_url": f"https://b{iid}.bandcamp.com/album/x",
                "url_hints": {"subdomain": f"b{iid}"}}

    blob = {
        "fan_data": {"fan_id": 9985893, "username": "guron",
                     "trackpipe_url": "https://bandcamp.com/guron"},
        "item_cache": {"collection": {}, "wishlist": {"1": item(1)}, "following_bands": {}},
        "collection_data": {"item_count": 0, "last_token": None},
        "wishlist_data": {"item_count": 3, "last_token": "1782:333:a::"},
        "following_bands_data": {"last_token": None},
    }
    enc = _html.escape(_json.dumps(blob), quote=True)
    return f'<div id="pagedata" data-blob="{enc}"></div>'


async def test_crawl_fan_collection_pages_all_wishlist(session: AsyncSession) -> None:
    # 1 wishlist item embedded + a wishlist token; the wishlist XHR adds 2 more.
    # All become is_wishlist fan_items (is_me), so curation can exclude them.
    fetcher = FakeFetcher({"bandcamp.com/guron": _fan_html_with_wishlist_token()})
    extra = [_album_item(9002, "https://x.bandcamp.com/album/w2"),
             _album_item(9003, "https://x.bandcamp.com/album/w3")]
    await crawl_fan_collection(
        session, fetcher, SEED_URL, is_me=True,
        collection_client=FakeCollectionClient(wishlist=extra),
        follows_client=FakeFollowsClient(),
    )
    wished = (await session.execute(
        select(func.count()).select_from(FanItem).where(FanItem.is_wishlist.is_(True))
    )).scalar_one()
    assert wished == 3  # 1 embedded + 2 paged


async def test_follows_not_paged_for_other_fans(session: AsyncSession) -> None:
    from app.db.models import Follow

    fetcher = FakeFetcher({"bandcamp.com/guron": _fan_html_with_follows_token()})
    called = FakeFollowsClient([ParsedBand(bandcamp_id=1, name="x", url="https://x.bandcamp.com")])
    await crawl_fan_collection(
        session, fetcher, SEED_URL, is_me=False,
        collection_client=FakeCollectionClient(), follows_client=called,
    )
    # not is_me → follows aren't ingested at all
    n = (await session.execute(select(func.count()).select_from(Follow))).scalar_one()
    assert n == 0


async def test_supporters_api_client_paginates_and_stops() -> None:
    seen_bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        body = _json.loads(request.content)
        seen_bodies.append(body)
        # Live XHR shape (verified): {results[], more_available} — NOT thumbs/more_thumbs_available.
        if body["token"] == "t0":
            return httpx.Response(200, json={
                "results": [{"fan_id": 1, "username": "alice",
                             "url": "https://bandcamp.com/alice", "token": "t1"}],
                "more_available": True,
            })
        return httpx.Response(200, json={
            "results": [{"fan_id": 2, "username": "bob",
                         "url": "https://bandcamp.com/bob", "token": "t2"}],
            "more_available": False,
        })

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = SupportersApiClient(http, count=40)
        users = [s.username async for s in client.iter_supporters(4255072328, "t0")]

    assert users == ["alice", "bob"]
    assert [b["token"] for b in seen_bodies] == ["t0", "t1"]
    assert all(
        b["tralbum_id"] == 4255072328 and b["tralbum_type"] == "a" for b in seen_bodies
    )


async def test_crawl_album_ingests_supporters_and_enqueues_them(
    session: AsyncSession,
) -> None:
    fetcher = FakeFetcher({ALBUM_URL: ALBUM_HTML})
    outcome = await crawl_album(
        session, fetcher, ALBUM_URL, supporters_client=FakeSupportersClient()
    )

    assert outcome.supporters == 3
    assert await _count(session, Album) == 1
    assert await _count(session, AlbumSupporter) == 3
    assert await _count(session, Fan) == 3

    # Each supporter's fan collection should now be queued.
    fans = (
        await session.execute(
            select(CrawlFrontier).where(CrawlFrontier.kind == CrawlKind.FAN_COLLECTION)
        )
    ).scalars().all()
    assert {f.url for f in fans} == {
        "https://bandcamp.com/guron",
        "https://bandcamp.com/moth_lord",
        "https://bandcamp.com/deepcrate",
    }


async def test_crawl_album_pages_extra_supporters(session: AsyncSession) -> None:
    fetcher = FakeFetcher({ALBUM_URL: ALBUM_HTML})
    # The thumbs XHR yields two supporters beyond the 3 embedded in the page.
    client = FakeSupportersClient([_supporter("late_fan"), _supporter("night_owl")])
    outcome = await crawl_album(session, fetcher, ALBUM_URL, supporters_client=client)

    assert outcome.supporters == 5
    assert await _count(session, AlbumSupporter) == 5
    fans = (
        await session.execute(
            select(CrawlFrontier).where(CrawlFrontier.kind == CrawlKind.FAN_COLLECTION)
        )
    ).scalars().all()
    assert "https://bandcamp.com/late_fan" in {f.url for f in fans}


async def test_crawl_album_propagates_depth(session: AsyncSession) -> None:
    fetcher = FakeFetcher({ALBUM_URL: ALBUM_HTML})
    await crawl_album(
        session, fetcher, ALBUM_URL, depth=1, max_depth=3,
        supporters_client=FakeSupportersClient(),
    )
    fans = (
        await session.execute(
            select(CrawlFrontier).where(CrawlFrontier.kind == CrawlKind.FAN_COLLECTION)
        )
    ).scalars().all()
    assert fans and all(f.depth == 2 for f in fans)  # children at depth+1


async def test_crawl_album_at_max_depth_enqueues_nothing(session: AsyncSession) -> None:
    fetcher = FakeFetcher({ALBUM_URL: ALBUM_HTML})
    # Album is ingested, but at depth == max_depth its supporters are NOT enqueued.
    outcome = await crawl_album(
        session, fetcher, ALBUM_URL, depth=3, max_depth=3,
        supporters_client=FakeSupportersClient(),
    )
    assert outcome.supporters == 3  # still ingested
    assert outcome.enqueued == 0
    assert await _count(session, CrawlFrontier) == 0


async def test_crawl_track_ingests_supporters_and_enqueues_them(
    session: AsyncSession,
) -> None:
    fetcher = FakeFetcher({TRACK_URL: TRACK_HTML})
    outcome = await crawl_track(
        session, fetcher, TRACK_URL, supporters_client=FakeSupportersClient()
    )

    assert outcome.kind == str(CrawlKind.TRACK)
    assert outcome.supporters == 3
    assert await _count(session, Track) == 1
    assert await _count(session, TrackSupporter) == 3
    assert await _count(session, AlbumSupporter) == 0
    assert await _count(session, Fan) == 3

    fans = (
        await session.execute(
            select(CrawlFrontier).where(CrawlFrontier.kind == CrawlKind.FAN_COLLECTION)
        )
    ).scalars().all()
    assert {f.url for f in fans} == {
        "https://bandcamp.com/tim-bruisson",
        "https://bandcamp.com/guron",
        "https://bandcamp.com/synth_wanderer",
    }


async def test_crawl_track_pages_extra_supporters(session: AsyncSession) -> None:
    fetcher = FakeFetcher({TRACK_URL: TRACK_HTML})
    client = FakeSupportersClient([_supporter("late_fan")])
    outcome = await crawl_track(session, fetcher, TRACK_URL, supporters_client=client)

    assert outcome.supporters == 4
    assert await _count(session, TrackSupporter) == 4


async def test_crawl_track_at_max_depth_enqueues_nothing(session: AsyncSession) -> None:
    fetcher = FakeFetcher({TRACK_URL: TRACK_HTML})
    outcome = await crawl_track(
        session, fetcher, TRACK_URL, depth=3, max_depth=3,
        supporters_client=FakeSupportersClient(),
    )
    assert outcome.supporters == 3  # still ingested
    assert outcome.enqueued == 0
    assert await _count(session, CrawlFrontier) == 0


async def test_runner_dispatches_track_kind(
    sessionmaker_: async_sessionmaker[AsyncSession],
) -> None:
    fetcher = FakeFetcher({TRACK_URL: TRACK_HTML})
    async with sessionmaker_() as s:
        await frontier.enqueue(s, TRACK_URL, CrawlKind.TRACK)
        await s.commit()

    outcomes = await runner.run_until_empty(
        sessionmaker_, fetcher, supporters_client=FakeSupportersClient(),
    )
    assert [o.kind for o in outcomes] == [str(CrawlKind.TRACK)]
    async with sessionmaker_() as s:
        assert await _count(s, Track) == 1
        assert await _count(s, TrackSupporter) == 3


# ── Runner (end-to-end over the frontier) ───────────────────────────────────────


async def test_runner_walks_the_graph(
    sessionmaker_: async_sessionmaker[AsyncSession],
) -> None:
    # Any /album/ or /track/ URL replays that fixture; guron's page the collection.
    fetcher = FakeFetcher({
        "bandcamp.com/guron": FAN_HTML, "/album/": ALBUM_HTML, "/track/": TRACK_HTML,
    })
    async with sessionmaker_() as s:
        await seed_fan_collection(s, SEED_URL)

    # Bound iterations: guron's collection routes to panchito + the owned track; the
    # other supporter fan pages have no fake route, so those entries error out and
    # the walk stops.
    outcomes = await runner.run_until_empty(
        sessionmaker_, fetcher, seed_url=SEED_URL,
        collection_client=FakeCollectionClient(),
        supporters_client=FakeSupportersClient(), max_iterations=25,
    )

    kinds = [o.kind for o in outcomes]
    assert str(CrawlKind.FAN_COLLECTION) in kinds
    assert str(CrawlKind.ALBUM) in kinds
    assert str(CrawlKind.TRACK) in kinds  # owned standalone tracks are walked too

    async with sessionmaker_() as s:
        # Seed fan marked is_me (its follows were recorded).
        me = (await s.execute(select(Fan).where(Fan.is_me.is_(True)))).scalars().all()
        assert len(me) == 1 and me[0].username == "guron"
        # The album and its supporters were ingested during the walk.
        assert await _count(s, Album) >= 1
        assert await _count(s, AlbumSupporter) == 3
        # …as were the owned track's own supporters.
        assert await _count(s, TrackSupporter) == 3
        # No entries left PENDING (all DONE or ERROR).
        assert await frontier.pending_count(s) == 0


async def test_runner_threads_seed_fan_id_into_the_filter(
    sessionmaker_: async_sessionmaker[AsyncSession],
) -> None:
    # The prune only works if seed_fan_id survives run_until_empty → process_one →
    # process_entry → crawl_fan_collection. Drive one depth-2 fan collection whose
    # owner owns an album on a followed label and check the album isn't queued.
    async with sessionmaker_() as s:
        fan_id = await _seed_fan_following(
            s, band_bandcamp_id=999999, band_url="https://cerebro-spinal.bandcamp.com"
        )
        await frontier.enqueue(s, SEED_URL, CrawlKind.FAN_COLLECTION, depth=2)
        await s.commit()

    fetcher = FakeFetcher({"bandcamp.com/guron": FAN_HTML})
    outcomes = await runner.run_until_empty(
        sessionmaker_, fetcher, seed_fan_id=fan_id,
        collection_client=FakeCollectionClient(), supporters_client=FakeSupportersClient(),
        max_depth=4, max_iterations=5,
    )

    assert [o.skipped_followed for o in outcomes] == [1]
    async with sessionmaker_() as s:
        assert ALBUM_URL not in await _frontier_urls(s)  # on the followed label's host
        assert TRACK_URL in await _frontier_urls(s)  # different host → still walked


async def test_budget_stops_the_run(
    sessionmaker_: async_sessionmaker[AsyncSession],
) -> None:
    # Pre-log 5 provider requests, then seed. With max_requests=5 the budget is
    # already spent, so run_until_empty must process nothing.
    async with sessionmaker_() as s:
        for _ in range(5):
            s.add(ProviderUsage(provider="nimble", ok=True))
        await seed_fan_collection(s, SEED_URL)
        await s.commit()

    fetcher = FakeFetcher({"bandcamp.com/guron": FAN_HTML})
    outcomes = await runner.run_until_empty(
        sessionmaker_, fetcher, seed_url=SEED_URL,
        collection_client=FakeCollectionClient(), supporters_client=FakeSupportersClient(),
        max_requests=5, max_iterations=25,
    )
    assert outcomes == []  # budget exhausted before any work
    assert fetcher.calls == []
    async with sessionmaker_() as s:
        assert await frontier.pending_count(s) == 1  # seed still pending


async def test_budget_helpers(session: AsyncSession) -> None:
    assert await runner.budget_exhausted(session, None) is False  # no cap
    for _ in range(3):
        session.add(ProviderUsage(provider="nimble", ok=True))
    session.add(ProviderUsage(provider="nimble", ok=False))  # failures don't count
    await session.commit()
    assert await runner.requests_used(session) == 3
    assert await runner.budget_exhausted(session, 3) is True
    assert await runner.budget_exhausted(session, 4) is False


async def test_runner_respects_max_depth(
    sessionmaker_: async_sessionmaker[AsyncSession],
) -> None:
    fetcher = FakeFetcher({
        "bandcamp.com/guron": FAN_HTML, "/album/": ALBUM_HTML, "/track/": TRACK_HTML,
    })
    async with sessionmaker_() as s:
        await seed_fan_collection(s, SEED_URL)  # depth 0

    # max_depth=1: seed (0) → owned albums/tracks (1) → album/track crawl at
    # depth 1 == max, so supporter fan-collections (depth 2) are never enqueued.
    await runner.run_until_empty(
        sessionmaker_, fetcher, seed_url=SEED_URL,
        collection_client=FakeCollectionClient(),
        supporters_client=FakeSupportersClient(), max_depth=1, max_iterations=25,
    )

    async with sessionmaker_() as s:
        fans = (
            await s.execute(
                select(CrawlFrontier).where(
                    CrawlFrontier.kind == CrawlKind.FAN_COLLECTION
                )
            )
        ).scalars().all()
        # Only the seed fan collection — no supporter collections were enqueued.
        assert {f.url for f in fans} == {SEED_URL}
        # Supporters were still ingested from the album and track pages.
        assert await _count(s, AlbumSupporter) == 3
        assert await _count(s, TrackSupporter) == 3
        assert await frontier.pending_count(s) == 0
