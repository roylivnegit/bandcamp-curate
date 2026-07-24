from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.crawl import frontier, runner
from app.crawl.seed import seed_fan_collection
from app.crawl.service import crawl_album, crawl_fan_collection
from app.db.base import Base
from app.db.models import Album, AlbumSupporter, CrawlFrontier, Fan, FanItem
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
    outcome = await crawl_fan_collection(session, fetcher, SEED_URL, is_me=True)

    assert outcome.items == 2  # one album + one track owned
    assert await _count(session, FanItem) == 2
    # The owned album should now be queued as an ALBUM crawl.
    albums = (
        await session.execute(
            select(CrawlFrontier).where(CrawlFrontier.kind == CrawlKind.ALBUM)
        )
    ).scalars().all()
    assert len(albums) == outcome.enqueued >= 1


async def test_crawl_album_ingests_supporters_and_enqueues_them(
    session: AsyncSession,
) -> None:
    fetcher = FakeFetcher({ALBUM_URL: ALBUM_HTML})
    outcome = await crawl_album(session, fetcher, ALBUM_URL)

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
        sessionmaker_, fetcher, seed_url=SEED_URL, max_iterations=25
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
