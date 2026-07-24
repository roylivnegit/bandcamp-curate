from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.bandcamp.collection_api import CollectionApiClient
from app.bandcamp.parse import ParsedBand, ParsedItem, ParsedSupporter
from app.bandcamp.supporters_api import SupportersApiClient
from app.crawl import frontier, runner
from app.crawl.seed import seed_fan_collection
from app.crawl.service import crawl_album, crawl_fan_collection
from app.db.base import Base
from app.db.models import Album, AlbumSupporter, CrawlFrontier, Fan, FanItem, ProviderUsage
from app.enums import CrawlKind, CrawlStatus
from app.scraping.base import FetchRequest, FetchResult

FIXTURES = Path(__file__).parent / "fixtures"
FAN_HTML = (FIXTURES / "fan_page.html").read_text()
ALBUM_HTML = (FIXTURES / "album_page.html").read_text()
ALBUM_URL = "https://cerebro-spinal.bandcamp.com/album/panchito"
SEED_URL = "https://bandcamp.com/guron"


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
    """Stands in for the collection_items XHR — yields preset extra items."""

    def __init__(self, items: list[ParsedItem] | None = None) -> None:
        self._items = items or []

    async def iter_items(
        self, fan_id: int, start_token: str, *, max_pages: int = 100
    ) -> AsyncIterator[ParsedItem]:
        for item in self._items:
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
    assert len(albums) == outcome.enqueued >= 2
    assert "https://paged.bandcamp.com/album/extra" in {a.url for a in albums}


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
        client = CollectionApiClient(http, count=40)
        items = [i async for i in client.iter_items(9985893, "tok0")]

    assert [i.item_id for i in items] == [1, 2]
    assert [b["older_than_token"] for b in seen_bodies] == ["tok0", "tok1"]
    assert all(b["fan_id"] == 9985893 and b["count"] == 40 for b in seen_bodies)


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


# ── Runner (end-to-end over the frontier) ───────────────────────────────────────


async def test_runner_walks_the_graph(
    sessionmaker_: async_sessionmaker[AsyncSession],
) -> None:
    # Any /album/ URL replays the album fixture; guron's page replays the collection.
    fetcher = FakeFetcher({"bandcamp.com/guron": FAN_HTML, "/album/": ALBUM_HTML})
    async with sessionmaker_() as s:
        await seed_fan_collection(s, SEED_URL)

    # Bound iterations: guron's collection routes to panchito; the other supporter
    # fan pages have no fake route, so those entries error out and the walk stops.
    outcomes = await runner.run_until_empty(
        sessionmaker_, fetcher, seed_url=SEED_URL,
        collection_client=FakeCollectionClient(),
        supporters_client=FakeSupportersClient(), max_iterations=25,
    )

    kinds = [o.kind for o in outcomes]
    assert str(CrawlKind.FAN_COLLECTION) in kinds
    assert str(CrawlKind.ALBUM) in kinds

    async with sessionmaker_() as s:
        # Seed fan marked is_me (its follows were recorded).
        me = (await s.execute(select(Fan).where(Fan.is_me.is_(True)))).scalars().all()
        assert len(me) == 1 and me[0].username == "guron"
        # The album and its supporters were ingested during the walk.
        assert await _count(s, Album) >= 1
        assert await _count(s, AlbumSupporter) == 3
        # No entries left PENDING (all DONE or ERROR).
        assert await frontier.pending_count(s) == 0


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
    fetcher = FakeFetcher({"bandcamp.com/guron": FAN_HTML, "/album/": ALBUM_HTML})
    async with sessionmaker_() as s:
        await seed_fan_collection(s, SEED_URL)  # depth 0

    # max_depth=1: seed (0) → owned albums (1) → album crawl at depth 1 == max,
    # so supporter fan-collections (depth 2) are never enqueued.
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
        # Supporters were still ingested from the album page.
        assert await _count(s, AlbumSupporter) == 3
        assert await frontier.pending_count(s) == 0
