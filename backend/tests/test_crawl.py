from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
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
    PAGES_PER_VISIT,
    crawl_album,
    crawl_fan_collection,
    crawl_track,
    followed_bands,
    kind_for_url,
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
    """Stands in for the collection_items / wishlist_items XHRs (URL-routed).

    Serves the supplied items one page at a time, mirroring the real client's
    `fetch_page` contract → (items, next_token, more_available). Tokens are just
    the index of the next page, which is enough to exercise resume.
    """

    def __init__(
        self, items: list[ParsedItem] | None = None,
        wishlist: list[ParsedItem] | None = None,
        per_page: int = 40,
    ) -> None:
        self._items = items or []
        self._wishlist = wishlist or []
        self.per_page = per_page
        self.pages_fetched = 0  # how many pagination requests this fake served

    def _page(self, source: list[ParsedItem], token: str):  # noqa: ANN202
        start = int(token) if str(token).isdigit() else 0
        chunk = source[start:start + self.per_page]
        nxt = start + self.per_page
        more = nxt < len(source)
        return chunk, (str(nxt) if more else None), more

    async def fetch_page(
        self, fan_id: int, older_than_token: str, *,
        count: int | None = None, url: str = COLLECTION_ITEMS_URL,
    ) -> tuple[list[ParsedItem], str | None, bool]:
        self.pages_fetched += 1
        source = self._wishlist if url == WISHLIST_ITEMS_URL else self._items
        return self._page(source, older_than_token)


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


@pytest_asyncio.fixture
async def concurrent_sessionmaker(tmp_path) -> AsyncIterator[  # noqa: ANN001
    async_sessionmaker[AsyncSession]
]:
    """A file-backed SQLite DB, for tests that need genuinely parallel sessions.

    The in-memory engine above hands every session the *same* connection
    (SQLAlchemy uses StaticPool for `sqlite://`), so concurrent work collides with
    "SQL statements in progress" — an artefact of the fixture, not of the code.
    Postgres gives each session its own connection, which is what production does.
    """
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'crawl.db'}",
        connect_args={"timeout": 30},  # SQLite serialises writers; wait, don't fail
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


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


# ── Per-scan frontier, reuse, and concurrency ──────────────────────────────────


async def test_frontier_is_scoped_per_scan(session: AsyncSession) -> None:
    # The same URL can be queued by two scans independently, and each only ever
    # claims its own. Before this, one scan drained a queue everyone shared.
    assert await frontier.enqueue(session, ALBUM_URL, CrawlKind.ALBUM, scan_id=1) is True
    assert await frontier.enqueue(session, ALBUM_URL, CrawlKind.ALBUM, scan_id=2) is True
    assert await frontier.enqueue(session, ALBUM_URL, CrawlKind.ALBUM, scan_id=1) is False
    await session.commit()

    assert await _count(session, CrawlFrontier) == 2
    claimed = await frontier.claim_next(session, scan_id=2)
    assert claimed is not None and claimed.scan_id == 2
    assert await frontier.pending_count(session, scan_id=1) == 1
    assert await frontier.pending_count(session, scan_id=2) == 0  # the one we claimed


async def test_a_scan_never_claims_legacy_entries(session: AsyncSession) -> None:
    """The July 2026 operator crawl left 11.5k rows behind and every later scan
    inherited them. Legacy rows (scan_id NULL) must be invisible to scans."""
    await frontier.enqueue(session, ALBUM_URL, CrawlKind.ALBUM)  # scan_id=None
    await session.commit()

    assert await frontier.claim_next(session, scan_id=7) is None  # not this scan's work
    assert await frontier.pending_count(session, scan_id=7) == 0
    # …but the legacy operator chain can still reach them.
    assert (await frontier.claim_next(session)) is not None


async def test_enqueue_survives_a_duplicate_race(session: AsyncSession) -> None:
    """Concurrent crawlers routinely discover the same album at the same instant.
    The loser of that race must not take the caller's pending work down with it —
    an ingested page is committed in the same transaction."""
    session.add(Fan(bandcamp_fan_id=99, username="pending_work", url=ME_URL))
    await session.flush()
    session.add(CrawlFrontier(scan_id=1, url=ALBUM_URL, kind=str(CrawlKind.ALBUM),
                              status=CrawlStatus.PENDING))
    await session.commit()

    # Simulate the racing insert landing between our select and our flush.
    session.add(Fan(bandcamp_fan_id=100, username="more_work", url="https://bandcamp.com/mw"))
    added = await frontier.enqueue(session, ALBUM_URL, CrawlKind.ALBUM, scan_id=1)
    await session.commit()

    assert added is False  # someone else got there
    assert await _count(session, Fan) == 2  # …and our unrelated work survived
    assert await _count(session, CrawlFrontier) == 1


async def test_reuse_skips_the_fetch_and_replays_the_fanout(
    sessionmaker_: async_sessionmaker[AsyncSession],
) -> None:
    """Scan 1 crawls an album; scan 2 wants the same album. The graph is global so
    re-fetching buys nothing — but skipping the fetch must NOT skip the fan-out, or
    scan 2's walk would silently dead-end at every page scan 1 had already seen."""
    fetcher = FakeFetcher({ALBUM_URL: ALBUM_HTML})
    async with sessionmaker_() as s:
        await frontier.enqueue(s, ALBUM_URL, CrawlKind.ALBUM, scan_id=1)
        await frontier.enqueue(s, ALBUM_URL, CrawlKind.ALBUM, scan_id=2)
        await s.commit()

    async with sessionmaker_() as s:  # scan 1: the real crawl
        first = await runner.process_one(
            s, fetcher, scan_id=1, supporters_client=FakeSupportersClient(), max_depth=3
        )
    assert first is not None and first.reused is False
    assert len(fetcher.calls) == 1
    assert first.enqueued == 3  # three supporters' collections, into scan 1

    async with sessionmaker_() as s:  # scan 2: same album, no credit
        second = await runner.process_one(
            s, fetcher, scan_id=2, supporters_client=FakeSupportersClient(), max_depth=3
        )
    assert second is not None and second.reused is True
    assert len(fetcher.calls) == 1  # NOT fetched again

    async with sessionmaker_() as s:
        # The fan-out was replayed from the stored supporter rows, into scan 2.
        fans = (await s.execute(
            select(CrawlFrontier).where(
                CrawlFrontier.scan_id == 2,
                CrawlFrontier.kind == CrawlKind.FAN_COLLECTION,
            )
        )).scalars().all()
        assert {f.url for f in fans} == {
            "https://bandcamp.com/guron",
            "https://bandcamp.com/moth_lord",
            "https://bandcamp.com/deepcrate",
        }
        assert all(f.depth == 1 for f in fans)  # same depth the live crawl would give
        album_entry = (await s.execute(
            select(CrawlFrontier).where(
                CrawlFrontier.scan_id == 2, CrawlFrontier.kind == CrawlKind.ALBUM
            )
        )).scalar_one()
        assert album_entry.status == CrawlStatus.DONE


async def test_the_owners_own_page_is_never_reused(
    sessionmaker_: async_sessionmaker[AsyncSession],
) -> None:
    """A collector's own page is very likely to have been crawled already as
    somebody else's neighbour — with is_me=False, so no wishlist and no follows.
    Reusing that for their own collection scan would mark the entry DONE, satisfy
    the self-crawl guard, and curate with no exclusions at all. It must re-crawl."""
    fetcher = FakeFetcher({"bandcamp.com/guron": FAN_HTML})
    async with sessionmaker_() as s:
        await frontier.enqueue(s, SEED_URL, CrawlKind.FAN_COLLECTION, scan_id=1)
        await frontier.enqueue(s, SEED_URL, CrawlKind.FAN_COLLECTION, scan_id=2)
        await s.commit()

    # Scan 1 crawls it as a neighbour (no seed_url match → is_me False).
    async with sessionmaker_() as s:
        await runner.process_one(
            s, fetcher, scan_id=1, collection_client=FakeCollectionClient(), max_depth=0
        )
    assert len(fetcher.calls) == 1

    # Scan 2 owns that page. Reuse would be silently wrong, so it must fetch again.
    async with sessionmaker_() as s:
        own = await runner.process_one(
            s, fetcher, scan_id=2, seed_url=SEED_URL,
            collection_client=FakeCollectionClient(), follows_client=FakeFollowsClient(),
            max_depth=0,
        )
    assert own is not None
    assert own.reused is False  # NOT reused…
    assert len(fetcher.calls) == 2  # …it really re-crawled

    # A different page in the same scan still reuses normally.
    async with sessionmaker_() as s:
        await frontier.enqueue(s, ALBUM_URL, CrawlKind.ALBUM, scan_id=1)
        await frontier.enqueue(s, ALBUM_URL, CrawlKind.ALBUM, scan_id=2)
        await s.commit()
    fetcher.routes[ALBUM_URL] = ALBUM_HTML
    async with sessionmaker_() as s:
        await runner.process_one(s, fetcher, scan_id=1,
                                 supporters_client=FakeSupportersClient(), max_depth=0)
    async with sessionmaker_() as s:
        other = await runner.process_one(
            s, fetcher, scan_id=2, seed_url=SEED_URL,
            supporters_client=FakeSupportersClient(), max_depth=0,
        )
    assert other is not None and other.reused is True


async def test_reuse_respects_max_depth(
    sessionmaker_: async_sessionmaker[AsyncSession],
) -> None:
    # At the depth bound a reused entry completes but must not replay children,
    # exactly as a live crawl there would ingest but not enqueue.
    fetcher = FakeFetcher({ALBUM_URL: ALBUM_HTML})
    async with sessionmaker_() as s:
        await frontier.enqueue(s, ALBUM_URL, CrawlKind.ALBUM, scan_id=1, depth=3)
        await frontier.enqueue(s, ALBUM_URL, CrawlKind.ALBUM, scan_id=2, depth=3)
        await s.commit()
    async with sessionmaker_() as s:
        await runner.process_one(s, fetcher, scan_id=1,
                                 supporters_client=FakeSupportersClient(), max_depth=3)
    async with sessionmaker_() as s:
        out = await runner.process_one(s, fetcher, scan_id=2,
                                       supporters_client=FakeSupportersClient(), max_depth=3)
    assert out is not None and out.reused is True and out.enqueued == 0


async def test_concurrent_drain_processes_each_entry_exactly_once(
    concurrent_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """A Nimble render is 3-35s of waiting, so the drain runs entries in parallel.
    Two workers landing on the same row would crawl it twice and pay twice."""
    urls = [f"https://b{i}.bandcamp.com/album/a{i}" for i in range(8)]
    fetcher = FakeFetcher({"/album/": ALBUM_HTML})
    async with concurrent_sessionmaker() as s:
        for u in urls:
            await frontier.enqueue(s, u, CrawlKind.ALBUM, scan_id=1)
        await s.commit()

    outcomes = await runner.run_until_empty(
        concurrent_sessionmaker, fetcher, scan_id=1,
        supporters_client=FakeSupportersClient(),
        max_depth=0, concurrency=4, max_iterations=20,
    )

    processed = [o.url for o in outcomes]
    assert sorted(processed) == sorted(urls)  # all of them…
    assert len(processed) == len(set(processed))  # …each exactly once
    async with concurrent_sessionmaker() as s:
        done = (await s.execute(
            select(CrawlFrontier).where(CrawlFrontier.status == CrawlStatus.DONE)
        )).scalars().all()
        assert len(done) == 8


# ── Bounded, resumable pagination ──────────────────────────────────────────────


def _fan_html_with_collection_token(token: str = "0") -> str:
    """A fan page whose collection has more pages behind it (`last_token` set)."""
    import html as _html
    import json as _json

    blob = {
        "fan_data": {"fan_id": 9985893, "username": "guron",
                     "trackpipe_url": "https://bandcamp.com/guron"},
        "item_cache": {"collection": {}, "wishlist": {}, "following_bands": {}},
        "collection_data": {"item_count": 1000, "last_token": token},
        "wishlist_data": {"last_token": None},
        "following_bands_data": {"last_token": None},
    }
    enc = _html.escape(_json.dumps(blob), quote=True)
    return f'<div id="pagedata" data-blob="{enc}"></div>'


def _many_items(n: int, start: int = 1) -> list[ParsedItem]:
    return [
        _album_item(start + i, f"https://b{start + i}.bandcamp.com/album/a{start + i}")
        for i in range(n)
    ]


class ExplodingCollectionClient(FakeCollectionClient):
    """Serves pages normally until `fail_on_page`, then raises — a crash mid-crawl."""

    def __init__(self, items: list[ParsedItem], *, per_page: int, fail_on_page: int) -> None:
        super().__init__(items, per_page=per_page)
        self._fail_on_page = fail_on_page

    async def fetch_page(self, *a, **kw):  # noqa: ANN002,ANN003,ANN202
        if self.pages_fetched + 1 == self._fail_on_page:
            raise RuntimeError("provider blew up mid-pagination")
        return await super().fetch_page(*a, **kw)


async def test_visit_is_capped_and_returns_a_cursor(session: AsyncSession) -> None:
    # 100 items at 4/page = 25 pages, far more than one visit's budget.
    fetcher = FakeFetcher({"bandcamp.com/guron": _fan_html_with_collection_token()})
    client = FakeCollectionClient(_many_items(100), per_page=4)

    outcome = await crawl_fan_collection(session, fetcher, SEED_URL, collection_client=client)

    assert client.pages_fetched == PAGES_PER_VISIT  # stopped at the budget, not the end
    assert outcome.items == PAGES_PER_VISIT * 4  # …and everything it read was ingested
    assert await _count(session, FanItem) == 40
    assert outcome.cursor is not None
    assert outcome.cursor["collection"] == "40"  # resume from item 40
    assert outcome.cursor["fan_id"] == 9985893


async def test_resume_continues_without_re_rendering_the_page(
    session: AsyncSession,
) -> None:
    """The whole point of the cursor: a resumed visit costs only its pagination.
    Re-rendering the fan page would burn a Nimble credit re-reading page one."""
    fetcher = FakeFetcher({"bandcamp.com/guron": _fan_html_with_collection_token()})
    client = FakeCollectionClient(_many_items(100), per_page=4)
    first = await crawl_fan_collection(session, fetcher, SEED_URL, collection_client=client)
    assert len(fetcher.calls) == 1  # the one render

    second = await crawl_fan_collection(
        session, fetcher, SEED_URL, collection_client=client, cursor=first.cursor
    )

    assert len(fetcher.calls) == 1  # NOT re-rendered — no second credit
    assert second.items == PAGES_PER_VISIT * 4  # the next 40 items
    assert await _count(session, FanItem) == 80  # 40 + 40, no overlap
    assert second.cursor is not None and second.cursor["collection"] == "80"


async def test_repeated_visits_drain_the_collection(session: AsyncSession) -> None:
    # 100 items / 4 per page = 25 pages → 3 visits (10 + 10 + 5).
    fetcher = FakeFetcher({"bandcamp.com/guron": _fan_html_with_collection_token()})
    client = FakeCollectionClient(_many_items(100), per_page=4)

    cursor, visits = None, 0
    while visits < 10:
        outcome = await crawl_fan_collection(
            session, fetcher, SEED_URL, collection_client=client, cursor=cursor
        )
        visits += 1
        cursor = outcome.cursor
        if cursor is None:
            break

    assert visits == 3
    assert cursor is None  # exhausted → the runner will mark it done
    assert await _count(session, FanItem) == 100  # every item, exactly once


async def test_pages_already_read_survive_a_crash(session: AsyncSession) -> None:
    """The regression this whole change exists for. The old loop held every page
    in memory and committed once at the end, so a failure discarded the lot —
    and the credits spent getting it. Now each page is durable when it lands."""
    fetcher = FakeFetcher({"bandcamp.com/guron": _fan_html_with_collection_token()})
    client = ExplodingCollectionClient(_many_items(100), per_page=4, fail_on_page=4)

    with pytest.raises(RuntimeError, match="blew up"):
        await crawl_fan_collection(session, fetcher, SEED_URL, collection_client=client)

    # Pages 1-3 were committed before the crash; only the 4th is lost.
    assert await _count(session, FanItem) == 12


async def test_runner_parks_a_partial_entry_as_pending_with_cursor(
    sessionmaker_: async_sessionmaker[AsyncSession],
) -> None:
    fetcher = FakeFetcher({"bandcamp.com/guron": _fan_html_with_collection_token()})
    client = FakeCollectionClient(_many_items(100), per_page=4)
    async with sessionmaker_() as s:
        await frontier.enqueue(s, SEED_URL, CrawlKind.FAN_COLLECTION)
        await s.commit()

    async with sessionmaker_() as s:
        outcome = await runner.process_one(s, fetcher, collection_client=client)
    assert outcome is not None and outcome.cursor is not None

    async with sessionmaker_() as s:
        entry = (await s.execute(
            select(CrawlFrontier).where(CrawlFrontier.kind == CrawlKind.FAN_COLLECTION)
        )).scalar_one()
        assert entry.status == CrawlStatus.PENDING  # back in the queue, not done
        assert entry.cursor["collection"] == "40"  # …carrying its bookmark
        assert entry.attempts == 1


async def test_runner_marks_done_and_clears_cursor_when_fully_paged(
    sessionmaker_: async_sessionmaker[AsyncSession],
) -> None:
    fetcher = FakeFetcher({"bandcamp.com/guron": _fan_html_with_collection_token()})
    client = FakeCollectionClient(_many_items(12), per_page=4)  # 3 pages < budget
    async with sessionmaker_() as s:
        await frontier.enqueue(s, SEED_URL, CrawlKind.FAN_COLLECTION)
        await s.commit()

    async with sessionmaker_() as s:
        await runner.process_one(s, fetcher, collection_client=client)

    async with sessionmaker_() as s:
        entry = (await s.execute(
            select(CrawlFrontier).where(CrawlFrontier.kind == CrawlKind.FAN_COLLECTION)
        )).scalar_one()
        assert entry.status == CrawlStatus.DONE
        assert entry.cursor is None


async def test_big_collections_take_turns_instead_of_hogging(
    sessionmaker_: async_sessionmaker[AsyncSession],
) -> None:
    """Two oversized collections must interleave: each gets a bounded visit before
    either gets a second. Without `attempts` in the claim ordering the first entry
    would be re-claimed forever and the second would never start.

    `max_depth=0` keeps the discovered albums out of the frontier so this asserts
    on the collection ordering alone.
    """
    fan_a, fan_b = "https://bandcamp.com/guron", "https://bandcamp.com/other"
    fetcher = FakeFetcher({
        "bandcamp.com/guron": _fan_html_with_collection_token(),
        # A distinct fan_id, so the two are separate Fan rows.
        "bandcamp.com/other": _fan_html_with_collection_token().replace(
            "9985893", "7777777").replace("guron", "other"),
    })
    client = FakeCollectionClient(_many_items(200), per_page=4)
    async with sessionmaker_() as s:
        await frontier.enqueue(s, fan_a, CrawlKind.FAN_COLLECTION)
        await frontier.enqueue(s, fan_b, CrawlKind.FAN_COLLECTION)
        await s.commit()

    visited = []
    for _ in range(4):
        async with sessionmaker_() as s:
            outcome = await runner.process_one(
                s, fetcher, collection_client=client, max_depth=0
            )
        visited.append(outcome.url)

    # Alternating, not A-A-A-A: both are still unfinished after two rounds each.
    assert visited == [fan_a, fan_b, fan_a, fan_b]
    async with sessionmaker_() as s:
        entries = (await s.execute(select(CrawlFrontier))).scalars().all()
        assert all(e.status == CrawlStatus.PENDING and e.attempts == 2 for e in entries)


async def test_run_until_empty_drains_a_multi_visit_collection(
    sessionmaker_: async_sessionmaker[AsyncSession],
) -> None:
    # 25 pages needs 3 visits; the runner should keep re-claiming the parked entry
    # until it's fully paged, then mark it done — no manual re-queue.
    fetcher = FakeFetcher({"bandcamp.com/guron": _fan_html_with_collection_token()})
    client = FakeCollectionClient(_many_items(100), per_page=4)
    async with sessionmaker_() as s:
        await frontier.enqueue(s, SEED_URL, CrawlKind.FAN_COLLECTION)
        await s.commit()

    outcomes = await runner.run_until_empty(
        sessionmaker_, fetcher, collection_client=client, max_depth=0, max_iterations=20
    )

    assert len(outcomes) == 3  # 10 + 10 + 5 pages
    assert [o.cursor is None for o in outcomes] == [False, False, True]
    async with sessionmaker_() as s:
        entry = (await s.execute(select(CrawlFrontier))).scalar_one()
        assert entry.status == CrawlStatus.DONE and entry.cursor is None
        assert await _count(s, FanItem) == 100
        assert await frontier.pending_count(s) == 0


async def test_a_run_that_stops_early_leaves_the_collection_resumable(
    sessionmaker_: async_sessionmaker[AsyncSession],
) -> None:
    """A run cut short mid-collection — in production by the credit budget, here
    by max_iterations — must not lose the pages already paid for. The entry stays
    PENDING with its bookmark, so the NEXT run resumes instead of re-buying them."""
    fetcher = FakeFetcher({"bandcamp.com/guron": _fan_html_with_collection_token()})
    client = FakeCollectionClient(_many_items(100), per_page=4)
    async with sessionmaker_() as s:
        await frontier.enqueue(s, SEED_URL, CrawlKind.FAN_COLLECTION)
        await s.commit()

    await runner.run_until_empty(
        sessionmaker_, fetcher, collection_client=client, max_depth=0, max_iterations=1
    )

    async with sessionmaker_() as s:
        entry = (await s.execute(select(CrawlFrontier))).scalar_one()
        assert entry.status == CrawlStatus.PENDING  # resumable, not failed
        assert entry.cursor is not None and entry.cursor["collection"] == "40"
        assert await _count(s, FanItem) == 40  # the pages we did pay for are kept

    # A later run picks up exactly where it left off, re-reading nothing.
    pages_before = client.pages_fetched
    await runner.run_until_empty(
        sessionmaker_, fetcher, collection_client=client, max_depth=0, max_iterations=20
    )
    async with sessionmaker_() as s:
        entry = (await s.execute(select(CrawlFrontier))).scalar_one()
        assert entry.status == CrawlStatus.DONE and entry.cursor is None
        assert await _count(s, FanItem) == 100
    assert client.pages_fetched - pages_before == 15  # the remaining pages, not 25


async def test_a_killed_visit_is_reclaimable_not_stranded(
    sessionmaker_: async_sessionmaker[AsyncSession],
) -> None:
    """A per-page commit also persists the IN_PROGRESS claim, so a process killed
    mid-visit (the 600s job_timeout that started all this) leaves a row nobody is
    working. A plain PENDING-only claim would strand it and those pages would be
    unreachable forever."""
    async with sessionmaker_() as s:
        await frontier.enqueue(s, SEED_URL, CrawlKind.FAN_COLLECTION)
        await s.commit()
    async with sessionmaker_() as s:  # claim, then "die" mid-visit
        await frontier.claim_next(s)
        await s.commit()

    async with sessionmaker_() as s:
        entry = (await s.execute(select(CrawlFrontier))).scalar_one()
        assert entry.status == CrawlStatus.IN_PROGRESS  # durably claimed
        assert await frontier.claim_next(s) is None  # nobody may steal a live claim
        # Once the claim goes stale, it must become reclaimable.
        reclaimed = await frontier.claim_next(s, stale_after=timedelta(seconds=0))
        assert reclaimed is not None and reclaimed.id == entry.id
        assert reclaimed.attempts == 2


async def test_crash_mid_visit_keeps_the_resume_bookmark(
    sessionmaker_: async_sessionmaker[AsyncSession],
) -> None:
    """Data durability isn't enough: without the bookmark, a retry re-buys every
    page it already paid for. The cursor must be committed with each page."""
    fetcher = FakeFetcher({"bandcamp.com/guron": _fan_html_with_collection_token()})
    client = ExplodingCollectionClient(_many_items(100), per_page=4, fail_on_page=6)
    async with sessionmaker_() as s:
        await frontier.enqueue(s, SEED_URL, CrawlKind.FAN_COLLECTION)
        await s.commit()

    async with sessionmaker_() as s:
        with pytest.raises(RuntimeError, match="blew up"):
            await runner.process_one(s, fetcher, collection_client=client, max_depth=0)

    async with sessionmaker_() as s:
        entry = (await s.execute(select(CrawlFrontier))).scalar_one()
        assert await _count(s, FanItem) == 20  # 5 pages committed before the crash
        assert entry.cursor is not None  # …and the bookmark survived with them
        assert entry.cursor["collection"] == "20"  # resume at item 20, not item 0
        assert entry.status == CrawlStatus.ERROR


async def test_killed_visit_recovers_and_resumes_without_re_buying_pages(
    sessionmaker_: async_sessionmaker[AsyncSession],
) -> None:
    """The whole recovery story end to end, as it would play out on a job timeout:
    killed mid-visit → stale claim reclaimed → resumed from the bookmark → done,
    paying only for the pages it hadn't already bought."""
    fetcher = FakeFetcher({"bandcamp.com/guron": _fan_html_with_collection_token()})
    client = FakeCollectionClient(_many_items(100), per_page=4)  # 25 pages
    async with sessionmaker_() as s:
        await frontier.enqueue(s, SEED_URL, CrawlKind.FAN_COLLECTION)
        await s.commit()

    # Claim and page 5, then vanish — no mark_done, no mark_error, no rollback.
    async with sessionmaker_() as s:
        entry = await frontier.claim_next(s)
        await crawl_fan_collection(
            s, fetcher, SEED_URL, collection_client=client, max_depth=0,
            pages_per_visit=5, entry=entry,
        )
    async with sessionmaker_() as s:
        row = (await s.execute(select(CrawlFrontier))).scalar_one()
        assert row.status == CrawlStatus.IN_PROGRESS  # abandoned claim
        assert row.cursor["collection"] == "20"  # …but the bookmark is durable
        assert await _count(s, FanItem) == 20

    pages_before = client.pages_fetched
    await runner.run_until_empty(
        sessionmaker_, fetcher, collection_client=client, max_depth=0,
        max_iterations=20, stale_after=timedelta(seconds=0),
    )

    async with sessionmaker_() as s:
        row = (await s.execute(select(CrawlFrontier))).scalar_one()
        assert row.status == CrawlStatus.DONE and row.cursor is None
        assert await _count(s, FanItem) == 100  # every item, still exactly once
    # 20 pages remained. Re-buying from the top would have cost 25.
    assert client.pages_fetched - pages_before == 20


async def test_cursor_is_checkpointed_on_every_page(session: AsyncSession) -> None:
    # The committed bookmark must track the pages actually ingested, so it can
    # never point earlier (re-buying) or later (silently skipping items).
    fetcher = FakeFetcher({"bandcamp.com/guron": _fan_html_with_collection_token()})
    client = FakeCollectionClient(_many_items(100), per_page=4)
    entry = CrawlFrontier(url=SEED_URL, kind=str(CrawlKind.FAN_COLLECTION),
                          status=CrawlStatus.IN_PROGRESS)
    session.add(entry)
    await session.commit()

    outcome = await crawl_fan_collection(
        session, fetcher, SEED_URL, collection_client=client, entry=entry
    )

    assert entry.cursor == outcome.cursor  # what's persisted == what's returned
    assert entry.cursor["collection"] == "40"


# ── Frontier kind comes from the URL, never from item_type ─────────────────────


def _track_item(item_id: int, url: str) -> ParsedItem:
    """A "track"-typed collection item — which is what `parse_collection_item`
    calls anything Bandcamp doesn't label an "album", `package` (vinyl/CD) included."""
    return ParsedItem(
        item_id=item_id, item_type="track",
        band=ParsedBand(bandcamp_id=item_id + 1, name="Paged Band"),
        title="A Package", url=url,
    )


def test_kind_for_url() -> None:
    assert kind_for_url("https://b.bandcamp.com/album/x") == CrawlKind.ALBUM
    assert kind_for_url("https://b.bandcamp.com/track/x") == CrawlKind.TRACK
    assert kind_for_url("https://B.BANDCAMP.COM/Album/X") == CrawlKind.ALBUM  # case-insensitive
    # Neither → None, so the caller skips rather than guessing a parser.
    assert kind_for_url("https://b.bandcamp.com/merch/x") is None
    assert kind_for_url("https://bandcamp.com/guron") is None
    assert kind_for_url("https://b.bandcamp.com/album") is None  # no slug
    assert kind_for_url("not a url") is None


async def test_track_typed_item_with_album_url_enqueues_as_album(
    session: AsyncSession,
) -> None:
    """Regression: a vinyl/`package` purchase arrives as item_type "track" carrying
    the /album/ URL. Enqueueing it as TRACK sends album HTML to `parse_track_page`,
    which silently writes a phantom Track under the *album's* id with the album's
    supporters attached. Route on the URL: it's an album page, so crawl it as one."""
    fetcher = FakeFetcher({"bandcamp.com/guron": FAN_HTML})
    package = _track_item(555001, "https://paged.bandcamp.com/album/vinyl-reissue")

    await crawl_fan_collection(
        session, fetcher, SEED_URL, collection_client=FakeCollectionClient([package])
    )

    entry = (
        await session.execute(
            select(CrawlFrontier).where(
                CrawlFrontier.url == "https://paged.bandcamp.com/album/vinyl-reissue"
            )
        )
    ).scalar_one()
    assert entry.kind == CrawlKind.ALBUM  # NOT TRACK, despite item_type == "track"


async def test_album_typed_item_with_track_url_enqueues_as_track(
    session: AsyncSession,
) -> None:
    # The mirror case — the URL wins in both directions, so there's no path where
    # a page reaches the parser built for the other kind.
    fetcher = FakeFetcher({"bandcamp.com/guron": FAN_HTML})
    mislabelled = _album_item(555001, "https://paged.bandcamp.com/track/single")

    await crawl_fan_collection(
        session, fetcher, SEED_URL, collection_client=FakeCollectionClient([mislabelled])
    )

    entry = (
        await session.execute(
            select(CrawlFrontier).where(
                CrawlFrontier.url == "https://paged.bandcamp.com/track/single"
            )
        )
    ).scalar_one()
    assert entry.kind == CrawlKind.TRACK


async def test_non_release_url_is_ingested_but_never_enqueued(
    session: AsyncSession,
) -> None:
    # A URL that's neither /album/ nor /track/ has no parser we can trust, so it is
    # ingested (ownership still counts) but never handed to one.
    fetcher = FakeFetcher({"bandcamp.com/guron": FAN_HTML})
    merch = _track_item(555001, "https://paged.bandcamp.com/merch/t-shirt")

    outcome = await crawl_fan_collection(
        session, fetcher, SEED_URL, collection_client=FakeCollectionClient([merch])
    )

    assert outcome.items == 3  # ingested like any other owned item
    assert outcome.enqueued == 2  # only the fixture's own album + track
    assert await _frontier_urls(session) == {ALBUM_URL, TRACK_URL}


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
    """Serves followed bands one page at a time (see FakeCollectionClient)."""

    def __init__(self, bands: list[ParsedBand] | None = None, per_page: int = 60) -> None:
        self._bands = bands or []
        self.per_page = per_page
        self.pages_fetched = 0

    async def fetch_page(
        self, fan_id: int, older_than_token: str, *, count: int | None = None
    ) -> tuple[list[ParsedBand], str | None, bool]:
        self.pages_fetched += 1
        start = int(older_than_token) if str(older_than_token).isdigit() else 0
        chunk = self._bands[start:start + self.per_page]
        nxt = start + self.per_page
        more = nxt < len(self._bands)
        return chunk, (str(nxt) if more else None), more


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
