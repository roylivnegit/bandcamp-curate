from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.auth.security import get_current_user
from app.crawl import frontier, runner, scan_service
from app.crawl.scan_service import (
    ENTRIES_PER_WORKER,
    advance_scan,
    claim_queued_scans,
    create_collection_scan,
    create_scan,
    finalize_scan,
    parse_seed_url,
    reclaim_stalled_scans,
    run_scan,
)
from app.db.base import Base
from app.db.models import CrawlFrontier, Fan, FanItem, ProviderUsage, Scan, ScanSeed, User
from app.db.session import get_session
from app.enums import CrawlKind, CrawlStatus, ScanKind, ScanStatus
from app.main import app

FIXTURES = Path(__file__).parent / "fixtures"
ALBUM_HTML = (FIXTURES / "album_page.html").read_text()
ALBUM_URL = "https://cerebro-spinal.bandcamp.com/album/panchito"
TRACK_HTML = (FIXTURES / "track_page.html").read_text()
TRACK_URL = "https://jscottg.bandcamp.com/track/return-of-the-king-original-mix"
FAN_HTML = (FIXTURES / "fan_page.html").read_text()
FAN_URL = "https://bandcamp.com/guron"  # the fan the fixture describes


# ── unit: URL parsing ──────────────────────────────────────────────────────────


def test_parse_seed_url() -> None:
    assert parse_seed_url("https://x.bandcamp.com/album/y") == (
        "https://x.bandcamp.com/album/y", "album",
    )
    assert parse_seed_url("http://LABEL.bandcamp.com/track/z?x=1")[1] == "track"
    # custom-domain album
    assert parse_seed_url("https://music.example.com/album/foo")[1] == "album"
    for bad in ("https://x.bandcamp.com/", "not a url", "https://x.bandcamp.com/merch/t"):
        with pytest.raises(ValueError, match="Bandcamp album or track"):
            parse_seed_url(bad)


# ── API ─────────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async with maker() as s:
        fan = Fan(bandcamp_fan_id=1, username="me", url="https://bandcamp.com/me", is_me=True)
        s.add(fan)
        await s.flush()
        user = User(username="me", password_hash="!", fan_id=fan.id)
        s.add(user)
        await s.commit()

    async def _override() -> AsyncIterator[AsyncSession]:
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = _override
    app.dependency_overrides[get_current_user] = lambda: user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


async def test_create_lists_gets_scan(client: AsyncClient) -> None:
    r = await client.post("/api/scans", json={"name": "Psy dig", "seeds": [ALBUM_URL, ALBUM_URL]})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Psy dig" and body["kind"] == "custom"
    assert body["status"] == "queued" and body["seed_count"] == 1  # deduped
    assert body["seeds"][0]["seed_type"] == "album"
    sid = body["id"]

    listed = (await client.get("/api/scans")).json()
    assert sid in {s["id"] for s in listed}

    detail = (await client.get(f"/api/scans/{sid}")).json()
    assert detail["id"] == sid and len(detail["seeds"]) == 1


async def test_create_validation(client: AsyncClient) -> None:
    async def post(name: str, seeds: list[str]):  # noqa: ANN202
        return await client.post("/api/scans", json={"name": name, "seeds": seeds})

    assert (await post("", [ALBUM_URL])).status_code == 400        # empty name
    assert (await post("n", [])).status_code == 400                # no seeds
    assert (await post("n", ["https://google.com"])).status_code == 400  # not a release URL


async def test_create_scan_seed_cap(client: AsyncClient) -> None:
    too_many = [f"https://x.bandcamp.com/album/a{i}" for i in range(501)]
    r = await client.post("/api/scans", json={"name": "n", "seeds": too_many})
    assert r.status_code == 400
    assert "too many seed" in r.json()["detail"]

    at_cap = too_many[:500]
    r = await client.post("/api/scans", json={"name": "n", "seeds": at_cap})
    assert r.status_code == 201
    assert r.json()["seed_count"] == 500


async def test_create_scan_with_track_seed(client: AsyncClient) -> None:
    r = await client.post(
        "/api/scans",
        json={"name": "Tracks + albums", "seeds": [ALBUM_URL, "https://x.bandcamp.com/track/t"]},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["seed_count"] == 2
    assert {s["seed_type"] for s in body["seeds"]} == {"album", "track"}


async def test_run_requeues(client: AsyncClient) -> None:
    sid = (await client.post("/api/scans", json={"name": "n", "seeds": [ALBUM_URL]})).json()["id"]
    # pretend it finished, then re-run → back to queued
    r = await client.post(f"/api/scans/{sid}/run")
    assert r.status_code == 200 and r.json()["status"] == "queued"
    assert (await client.post("/api/scans/999999/run")).status_code == 404


async def test_delete_scan_and_protect_collection(client: AsyncClient) -> None:
    sid = (await client.post("/api/scans", json={"name": "n", "seeds": [ALBUM_URL]})).json()["id"]
    assert (await client.delete(f"/api/scans/{sid}")).status_code == 200
    assert (await client.get(f"/api/scans/{sid}")).status_code == 404
    assert (await client.delete("/api/scans/999999")).status_code == 404


async def test_delete_scan_drops_frontier_and_usage_rows(sessionmaker_) -> None:  # noqa: ANN001
    # A scan that has actually run leaves CrawlFrontier/ProviderUsage rows
    # behind (neither FK declares ondelete=CASCADE, unlike ScanSeed/
    # Recommendation) -- delete_scan must clean those up itself or they're
    # orphaned (silently on SQLite here; an IntegrityError on real Postgres).
    async with sessionmaker_() as s:
        fan = Fan(bandcamp_fan_id=1, username="me", url="https://bandcamp.com/me", is_me=True)
        s.add(fan)
        await s.flush()
        user = User(username="me", password_hash="!", fan_id=fan.id)
        s.add(user)
        await s.flush()
        scan = Scan(user_id=user.id, name="n", kind=str(ScanKind.CUSTOM),
                    status=str(ScanStatus.DONE))
        s.add(scan)
        await s.flush()
        sid = scan.id
        s.add_all([
            CrawlFrontier(scan_id=sid, url=ALBUM_URL, kind=str(CrawlKind.ALBUM)),
            ProviderUsage(scan_id=sid, provider="test"),
        ])
        await s.commit()

    async def _override() -> AsyncIterator[AsyncSession]:
        async with sessionmaker_() as s:
            yield s

    app.dependency_overrides[get_session] = _override
    app.dependency_overrides[get_current_user] = lambda: user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.delete(f"/api/scans/{sid}")
    app.dependency_overrides.clear()
    assert r.status_code == 200

    async with sessionmaker_() as s:
        assert (
            await s.execute(select(CrawlFrontier).where(CrawlFrontier.scan_id == sid))
        ).first() is None
        assert (
            await s.execute(select(ProviderUsage).where(ProviderUsage.scan_id == sid))
        ).first() is None


# ── run_scan orchestration (over the fixture, no network) ────────────────────────


class FakeFetcher:
    def __init__(self, routes: dict[str, str]) -> None:
        self.routes = routes

    async def fetch(self, request):  # noqa: ANN001,ANN202
        from app.scraping.base import FetchResult
        for needle, html in self.routes.items():
            if needle in request.url:
                return FetchResult(
                    url=request.url, provider="fake", status_code=200, ok=True, html=html
                )
        raise AssertionError(f"no route for {request.url}")


class FakeSupportersClient:
    async def iter_supporters(self, *a, **kw):  # noqa: ANN002,ANN003,ANN202
        return
        yield  # pragma: no cover


@pytest_asyncio.fixture
async def sessionmaker_() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_claim_queued_scans(sessionmaker_) -> None:  # noqa: ANN001
    async with sessionmaker_() as s:
        user = User(username="me", password_hash="!")
        s.add(user)
        await s.flush()
        s.add_all([
            Scan(user_id=user.id, name="a",
                 kind=str(ScanKind.CUSTOM), status=str(ScanStatus.QUEUED)),
            Scan(user_id=user.id, name="b",
                 kind=str(ScanKind.CUSTOM), status=str(ScanStatus.DONE)),
        ])
        await s.commit()
        ids = await claim_queued_scans(s)
        assert len(ids) == 1
        # claimed scan is now running; a second claim finds nothing
        assert await claim_queued_scans(s) == []


async def test_run_scan_crawls_resolves_and_curates(sessionmaker_) -> None:  # noqa: ANN001
    # A custom scan seeded with the album fixture: run_scan should crawl it, resolve
    # the seed to the ingested album, curate, and mark the scan done.
    async with sessionmaker_() as s:
        # curation needs a User linked to a Fan as the exclusion base (a prior
        # collection crawl would have created both).
        fan = Fan(bandcamp_fan_id=1, username="me", url="https://bandcamp.com/me", is_me=True)
        s.add(fan)
        await s.flush()
        user = User(username="me", password_hash="!", fan_id=fan.id)
        s.add(user)
        await s.commit()
        scan = await create_scan(s, user.id, "Panchito dig", [ALBUM_URL])
        scan_id = scan.id

    fetcher = FakeFetcher({ALBUM_URL: ALBUM_HTML, "/album/": ALBUM_HTML})
    done = await run_scan(
        sessionmaker_, fetcher, scan_id,
        supporters_client=FakeSupportersClient(), max_depth=1, max_requests_per_scan=50,
    )
    assert done.status == str(ScanStatus.DONE)
    assert "recommendations" in done.stats

    async with sessionmaker_() as s:
        seed = (await s.execute(select(ScanSeed).where(ScanSeed.scan_id == scan_id))).scalar_one()
        assert seed.resolved_album_id is not None  # seed resolved to the crawled album


async def test_run_scan_passes_the_owners_fan_to_the_drain(
    sessionmaker_, monkeypatch: pytest.MonkeyPatch,  # noqa: ANN001
) -> None:
    # The followed-artist prune keys off the *scan owner's* fan, so run_scan must
    # resolve it and hand it to the frontier drain (see crawl.service.followed_bands).
    async with sessionmaker_() as s:
        fan = Fan(bandcamp_fan_id=1, username="me", url="https://bandcamp.com/me")
        s.add(fan)
        await s.flush()
        user = User(username="me", password_hash="!", fan_id=fan.id)
        s.add(user)
        await s.commit()
        scan = await create_scan(s, user.id, "Panchito dig", [ALBUM_URL])
        scan_id, fan_id = scan.id, fan.id

    seen: dict = {}
    real_run = runner.run_until_empty

    async def spy(*a, **kw):  # noqa: ANN002,ANN003,ANN202
        seen.update(kw)
        return await real_run(*a, **kw)

    monkeypatch.setattr(runner, "run_until_empty", spy)
    await run_scan(
        sessionmaker_, FakeFetcher({ALBUM_URL: ALBUM_HTML}), scan_id,
        supporters_client=FakeSupportersClient(), max_depth=1, max_requests_per_scan=50,
    )
    assert seen["seed_fan_id"] == fan_id


async def test_slices_pick_up_the_owner_fan_once_it_exists(sessionmaker_) -> None:  # noqa: ANN001
    """The owner's Fan is created BY the crawl — their page is an ordinary frontier
    entry now — so the first slice legitimately has no `seed_fan_id`. Every slice
    after it must carry the id, since that's what drives the followed-artist prune."""
    async with sessionmaker_() as s:
        user = User(username="guron", password_hash="!", bandcamp_fan_url=FAN_URL)
        s.add(user)
        await s.flush()
        scan = await create_collection_scan(s, user)
        user_id, scan_id = user.id, scan.id
        assert user.fan_id is None

    seen: list = []
    real_run = runner.run_until_empty

    async def spy(*a, **kw):  # noqa: ANN002,ANN003,ANN202
        seen.append(kw.get("seed_fan_id"))
        return await real_run(*a, **kw)

    fetcher = FakeFetcher({FAN_URL: FAN_HTML, "/album/": ALBUM_HTML})
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(runner, "run_until_empty", spy)
        for _ in range(2):
            await advance_scan(
                sessionmaker_, fetcher, scan_id,
                collection_client=FakeCollectionClient(), follows_client=FakeFollowsClient(),
                supporters_client=FakeSupportersClient(), max_depth=1, max_requests_per_scan=50,
                slice_entries=1,  # one entry per slice, so the fan page is slice 1
            )

    async with sessionmaker_() as s:
        crawled_fan_id = (await s.get(User, user_id)).fan_id
    assert crawled_fan_id is not None
    assert seen[0] is None  # the Fan didn't exist yet
    assert seen[1] == crawled_fan_id  # …and the next slice picked it up


async def test_collection_scan_is_chained_not_drained_in_one_go(sessionmaker_) -> None:  # noqa: ANN001
    """`advance_scan` must stop at its slice bound and report more work, rather
    than draining the frontier inside one job the way the old run_scan did."""
    async with sessionmaker_() as s:
        user = User(username="guron", password_hash="!", bandcamp_fan_url=FAN_URL)
        s.add(user)
        await s.flush()
        scan = await create_collection_scan(s, user)
        scan_id = scan.id

    fetcher = FakeFetcher({FAN_URL: FAN_HTML, "/album/": ALBUM_HTML})
    more = await advance_scan(
        sessionmaker_, fetcher, scan_id,
        collection_client=FakeCollectionClient(), follows_client=FakeFollowsClient(),
        supporters_client=FakeSupportersClient(), max_depth=1, max_requests_per_scan=50,
        slice_entries=1,
    )
    assert more is True  # the owned albums it just found are still queued

    async with sessionmaker_() as s:
        scan = await s.get(Scan, scan_id)
        assert scan.status == str(ScanStatus.RUNNING)  # not finalized mid-chain
        assert await frontier.pending_count(s, scan_id=scan_id) > 0
        # …and that work belongs to THIS scan, not a shared pool.
        assert await frontier.pending_count(s, scan_id=scan_id + 999) == 0


async def test_a_slice_offers_several_entries_per_worker(sessionmaker_) -> None:  # noqa: ANN001
    """Entries are the safety cap; TIME bounds a slice. Workers need more entries
    than there are workers, or every one is busy from the first instant, the
    deadline is never re-checked, and the slice runs as long as its slowest entry —
    which produced 4-minute slices that never completed, so the post-slice curate
    never ran and the live feed stayed empty."""
    async with sessionmaker_() as s:
        user = User(username="guron", password_hash="!", bandcamp_fan_url=FAN_URL)
        s.add(user)
        await s.flush()
        scan = await create_collection_scan(s, user)
        scan_id = scan.id

    seen: list = []
    real_run = runner.run_until_empty

    async def spy(*a, **kw):  # noqa: ANN002,ANN003,ANN202
        seen.append(kw.get("max_iterations"))
        return await real_run(*a, **kw)

    fetcher = FakeFetcher({FAN_URL: FAN_HTML, "/album/": ALBUM_HTML})

    async def slice_once(entries: int, workers: int) -> None:
        await advance_scan(
            sessionmaker_, fetcher, scan_id,
            collection_client=FakeCollectionClient(), follows_client=FakeFollowsClient(),
            supporters_client=FakeSupportersClient(), max_depth=1, max_requests_per_scan=50,
            slice_entries=entries, concurrency=workers,
        )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(runner, "run_until_empty", spy)
        await slice_once(2, 6)    # slice 1: fresh-scan special case, forced to 1
        await slice_once(2, 6)    # 6 workers x 8 = 48
        await slice_once(99, 3)   # floor wins when it is the larger

    # Slice 1 is the fresh-collection-scan special case: one entry on its own, so
    # the owner's Fan exists (and the followed-artist prune works) from slice 2.
    assert seen == [1, 6 * ENTRIES_PER_WORKER, 99]


async def test_the_slice_chain_is_bounded(sessionmaker_) -> None:  # noqa: ANN001
    """The ARQ chain re-enqueues purely on "more work?", so without a persisted
    counter a perpetually-nonempty frontier would spawn jobs forever and leave the
    scan running indefinitely. The bound lives in start_scan so both the chain and
    the blocking runner inherit it."""
    async with sessionmaker_() as s:
        user = User(username="guron", password_hash="!", bandcamp_fan_url=FAN_URL)
        s.add(user)
        await s.flush()
        scan = await create_collection_scan(s, user)
        scan_id = scan.id

    fetcher = FakeFetcher({FAN_URL: FAN_HTML, "/album/": ALBUM_HTML})

    async def slice_once():  # noqa: ANN202
        return await advance_scan(
            sessionmaker_, fetcher, scan_id,
            collection_client=FakeCollectionClient(), follows_client=FakeFollowsClient(),
            supporters_client=FakeSupportersClient(), max_depth=1, max_requests_per_scan=50,
            slice_entries=1,
        )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(scan_service, "MAX_SCAN_SLICES", 2)
        assert await slice_once() is True  # slice 1 leaves work queued
        await slice_once()  # slice 2 — at the bound. Whether work remains depends
        # on the fixture's size and isn't the point; the refusal below is.
        with pytest.raises(ValueError, match="exceeded 2 slices"):
            await slice_once()  # slice 3 — refuses rather than queueing more

    async with sessionmaker_() as s:
        assert (await s.get(Scan, scan_id)).stats["slices_run"] == 3


async def test_slice_count_resets_on_a_fresh_run(sessionmaker_) -> None:  # noqa: ANN001
    # Re-running a scan (status back to queued) must not inherit the previous
    # run's slice count, or a long-lived scan could never be re-run.
    async with sessionmaker_() as s:
        user = User(username="guron", password_hash="!", bandcamp_fan_url=FAN_URL)
        s.add(user)
        await s.flush()
        scan = await create_collection_scan(s, user)
        scan_id = scan.id

    fetcher = FakeFetcher({FAN_URL: FAN_HTML, "/album/": ALBUM_HTML})
    kwargs = dict(
        collection_client=FakeCollectionClient(), follows_client=FakeFollowsClient(),
        supporters_client=FakeSupportersClient(), max_depth=1, max_requests_per_scan=50,
        slice_entries=1,
    )
    await advance_scan(sessionmaker_, fetcher, scan_id, **kwargs)
    await advance_scan(sessionmaker_, fetcher, scan_id, **kwargs)
    async with sessionmaker_() as s:
        scan = await s.get(Scan, scan_id)
        assert scan.stats["slices_run"] == 2
        scan.status = str(ScanStatus.QUEUED)  # what POST /api/scans/{id}/run does
        await s.commit()

    await advance_scan(sessionmaker_, fetcher, scan_id, **kwargs)
    async with sessionmaker_() as s:
        assert (await s.get(Scan, scan_id)).stats["slices_run"] == 1  # counted afresh


async def test_first_slice_of_a_fresh_collection_scan_takes_one_entry(
    sessionmaker_,  # noqa: ANN001
) -> None:
    """The owner's Fan doesn't exist until their page is ingested, and seed_fan_id
    is fixed for a whole slice — so a multi-entry first slice would crawl the rest
    of itself with the followed-artist prune off, spending credits on albums
    curation drops anyway. That first page gets a slice to itself."""
    async with sessionmaker_() as s:
        user = User(username="guron", password_hash="!", bandcamp_fan_url=FAN_URL)
        s.add(user)
        await s.flush()
        scan = await create_collection_scan(s, user)
        scan_id, user_id = scan.id, user.id

    fetcher = FakeFetcher({FAN_URL: FAN_HTML, "/album/": ALBUM_HTML})
    # slice_entries=10, but the fresh-scan case must still stop after one entry.
    await advance_scan(
        sessionmaker_, fetcher, scan_id,
        collection_client=FakeCollectionClient(), follows_client=FakeFollowsClient(),
        supporters_client=FakeSupportersClient(), max_depth=1, max_requests_per_scan=50,
        slice_entries=10,
    )

    async with sessionmaker_() as s:
        done = (
            await s.execute(
                select(CrawlFrontier).where(CrawlFrontier.status == CrawlStatus.DONE)
            )
        ).scalars().all()
        assert [e.url for e in done] == [FAN_URL]  # only the owner's page
        assert (await s.get(User, user_id)).fan_id is not None  # …and it linked the Fan


async def test_finalize_refuses_a_half_crawled_collection(sessionmaker_) -> None:  # noqa: ANN001
    """Curating on a partly-read collection would silently surface artists the user
    already owns or follows, with nothing in the feed explaining why. Finalizing
    must refuse while the owner's own page is still unfinished."""
    async with sessionmaker_() as s:
        user = User(username="guron", password_hash="!", bandcamp_fan_url=FAN_URL)
        s.add(user)
        await s.flush()
        scan = await create_collection_scan(s, user)
        scan_id = scan.id
        # Own page enqueued but never crawled — exactly the out-of-credits state.
        await frontier.enqueue(s, FAN_URL, CrawlKind.FAN_COLLECTION, scan_id=scan_id)
        await s.commit()

    with pytest.raises(ValueError, match="only partly crawled"):
        await finalize_scan(sessionmaker_, scan_id)


async def test_run_scan_with_mixed_album_and_track_seeds(sessionmaker_) -> None:  # noqa: ANN001
    # A scan seeded with BOTH an album URL and a track URL, any mix: both should
    # be crawled, both resolved, and both contribute taste-neighbours.
    async with sessionmaker_() as s:
        fan = Fan(bandcamp_fan_id=1, username="me", url="https://bandcamp.com/me", is_me=True)
        s.add(fan)
        await s.flush()
        user = User(username="me", password_hash="!", fan_id=fan.id)
        s.add(user)
        await s.commit()
        scan = await create_scan(s, user.id, "Mixed dig", [ALBUM_URL, TRACK_URL])
        scan_id = scan.id

    fetcher = FakeFetcher({ALBUM_URL: ALBUM_HTML, TRACK_URL: TRACK_HTML})
    done = await run_scan(
        sessionmaker_, fetcher, scan_id,
        supporters_client=FakeSupportersClient(), max_depth=1, max_requests_per_scan=50,
    )
    assert done.status == str(ScanStatus.DONE)

    async with sessionmaker_() as s:
        seeds = (
            await s.execute(select(ScanSeed).where(ScanSeed.scan_id == scan_id))
        ).scalars().all()
        by_type = {sd.seed_type: sd for sd in seeds}
        assert by_type["album"].resolved_album_id is not None
        assert by_type["track"].resolved_track_id is not None


# ── collection-scan onboarding (a fresh signup's own crawl) ─────────────────────


class FakeCollectionClient:
    """The collection/wishlist XHRs return nothing extra beyond the embedded page,
    so every page is empty and `more_available` is false — one visit finishes."""

    async def fetch_page(self, *a, **kw):  # noqa: ANN002,ANN003,ANN202
        return [], None, False


class FakeFollowsClient:
    async def fetch_page(self, *a, **kw):  # noqa: ANN002,ANN003,ANN202
        return [], None, False


async def _run_collection_scan(sessionmaker_, user_id: int, scan_id: int):  # noqa: ANN001,ANN202
    fetcher = FakeFetcher({FAN_URL: FAN_HTML, "/album/": ALBUM_HTML})
    return await run_scan(
        sessionmaker_, fetcher, scan_id,
        collection_client=FakeCollectionClient(), follows_client=FakeFollowsClient(),
        supporters_client=FakeSupportersClient(), max_depth=1, max_requests_per_scan=50,
    )


async def test_collection_scan_crawls_the_users_own_fan_page(sessionmaker_) -> None:  # noqa: ANN001
    """A fresh signup: no Fan row yet, a queued kind=collection scan with no seeds.
    run_scan must crawl the user's own fan page, link user.fan_id to the ingested
    Fan, enqueue their owned albums, and curate — the whole onboarding path."""
    async with sessionmaker_() as s:
        user = User(username="guron", password_hash="!", bandcamp_fan_url=FAN_URL)
        s.add(user)
        await s.flush()
        scan = await create_collection_scan(s, user)
        user_id, scan_id = user.id, scan.id
        assert user.fan_id is None  # nothing crawled yet

    done = await _run_collection_scan(sessionmaker_, user_id, scan_id)
    assert done.status == str(ScanStatus.DONE)

    async with sessionmaker_() as s:
        user = await s.get(User, user_id)
        assert user.fan_id is not None  # linked to the ingested Fan
        fan = await s.get(Fan, user.fan_id)
        assert fan.username == "guron" and fan.is_me is True
        # Their owned items were ingested and their albums enqueued for the walk.
        owned = (
            await s.execute(select(FanItem).where(FanItem.fan_id == fan.id))
        ).scalars().all()
        assert owned


async def test_collection_scan_rerun_is_idempotent(sessionmaker_) -> None:  # noqa: ANN001
    """Re-running the collection scan (the "refresh my collection" path) must not
    duplicate the Fan/ownership rows or change which Fan the user points at."""
    async with sessionmaker_() as s:
        user = User(username="guron", password_hash="!", bandcamp_fan_url=FAN_URL)
        s.add(user)
        await s.flush()
        scan = await create_collection_scan(s, user)
        user_id, scan_id = user.id, scan.id

    await _run_collection_scan(sessionmaker_, user_id, scan_id)
    async with sessionmaker_() as s:
        first_fan_id = (await s.get(User, user_id)).fan_id
        fans_before = len((await s.execute(select(Fan))).scalars().all())
        items_before = len((await s.execute(select(FanItem))).scalars().all())

    await _run_collection_scan(sessionmaker_, user_id, scan_id)
    async with sessionmaker_() as s:
        assert (await s.get(User, user_id)).fan_id == first_fan_id
        assert len((await s.execute(select(Fan))).scalars().all()) == fans_before
        assert len((await s.execute(select(FanItem))).scalars().all()) == items_before


async def test_collection_scan_without_a_fan_url_errors_cleanly(sessionmaker_) -> None:  # noqa: ANN001
    async with sessionmaker_() as s:
        user = User(username="nourl", password_hash="!", bandcamp_fan_url=None)
        s.add(user)
        await s.flush()
        scan = await create_collection_scan(s, user)
        user_id, scan_id = user.id, scan.id

    with pytest.raises(ValueError, match="bandcamp_fan_url"):
        await _run_collection_scan(sessionmaker_, user_id, scan_id)

    async with sessionmaker_() as s:  # failure recorded on the scan, not swallowed
        scan = await s.get(Scan, scan_id)
        assert scan.status == str(ScanStatus.ERROR) and "bandcamp_fan_url" in scan.error


# ── Stalled-chain recovery and incremental curation ────────────────────────────


async def test_a_dead_chain_is_revived(sessionmaker_) -> None:  # noqa: ANN001
    """A scan runs as jobs that re-enqueue themselves. Kill one — job timeout,
    worker restart, laptop asleep — and nothing schedules the next, leaving the
    scan `running` forever because the poller only claims `queued`. That stranded
    three scans on 2026-08-06, each needing a manual nudge."""
    from datetime import UTC, datetime, timedelta

    async with sessionmaker_() as s:
        user = User(username="me", password_hash="!")
        s.add(user)
        await s.flush()
        cold = Scan(user_id=user.id, name="cold", kind=str(ScanKind.CUSTOM),
                    status=str(ScanStatus.RUNNING),
                    stats={"last_slice_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat()})
        warm = Scan(user_id=user.id, name="warm", kind=str(ScanKind.CUSTOM),
                    status=str(ScanStatus.RUNNING),
                    stats={"last_slice_at": datetime.now(UTC).isoformat()})
        never = Scan(user_id=user.id, name="never", kind=str(ScanKind.CUSTOM),
                     status=str(ScanStatus.RUNNING), stats={})
        finished = Scan(user_id=user.id, name="done", kind=str(ScanKind.CUSTOM),
                        status=str(ScanStatus.DONE), stats={})
        s.add_all([cold, warm, never, finished])
        await s.commit()
        ids = {"cold": cold.id, "warm": warm.id, "never": never.id, "done": finished.id}

    async with sessionmaker_() as s:
        reclaimed = await reclaim_stalled_scans(s, timedelta(minutes=15))

    assert set(reclaimed) == {ids["cold"], ids["never"]}  # cold + no-heartbeat
    async with sessionmaker_() as s:
        assert (await s.get(Scan, ids["warm"])).status == str(ScanStatus.RUNNING)  # in flight
        assert (await s.get(Scan, ids["done"])).status == str(ScanStatus.DONE)  # untouched
        assert (await s.get(Scan, ids["cold"])).status == str(ScanStatus.QUEUED)


async def test_a_slice_writes_a_heartbeat(sessionmaker_) -> None:  # noqa: ANN001
    # The watchdog above is only as good as the heartbeat it ages out.
    async with sessionmaker_() as s:
        user = User(username="guron", password_hash="!", bandcamp_fan_url=FAN_URL)
        s.add(user)
        await s.flush()
        scan = await create_collection_scan(s, user)
        scan_id = scan.id

    await advance_scan(
        sessionmaker_, FakeFetcher({FAN_URL: FAN_HTML, "/album/": ALBUM_HTML}), scan_id,
        collection_client=FakeCollectionClient(), follows_client=FakeFollowsClient(),
        supporters_client=FakeSupportersClient(), max_depth=1, max_requests_per_scan=50,
    )

    async with sessionmaker_() as s:
        assert "last_slice_at" in (await s.get(Scan, scan_id)).stats


def _fan_html_with_more_pages() -> str:
    """A fan page whose collection has further pages behind it, so one bounded
    visit leaves the entry PENDING with a cursor — a partially-read collection."""
    import html as _html
    import json as _json

    blob = {
        "fan_data": {"fan_id": 9985893, "username": "guron",
                     "trackpipe_url": FAN_URL},
        "item_cache": {"collection": {}, "wishlist": {}, "following_bands": {}},
        "collection_data": {"item_count": 5000, "last_token": "0"},
        "wishlist_data": {"last_token": None},
        "following_bands_data": {"last_token": None},
    }
    return f'<div id="pagedata" data-blob="{_html.escape(_json.dumps(blob), quote=True)}"></div>'


class EndlessCollectionClient:
    """Always reports another page, so a bounded visit can never finish.

    The token must advance: `_next_token` deliberately stops when a provider
    echoes the same token back, which would otherwise end this stream after two
    pages and complete the entry.
    """

    def __init__(self) -> None:
        self.page = 0

    async def fetch_page(self, *a, **kw):  # noqa: ANN002,ANN003,ANN202
        self.page += 1
        return [], f"tok{self.page}", True


async def _curate_calls_for(sessionmaker_, who: str, fan_html: str, client) -> list[int]:  # noqa: ANN001
    """Run one curating slice for a fresh collection scan; return the curate calls."""
    import app.curation.engine as engine

    calls: list[int] = []

    async def fake_curate(session, *, scan_id, **kw):  # noqa: ANN001,ANN003,ANN202
        calls.append(scan_id)
        return []

    async with sessionmaker_() as s:
        user = User(username=who, password_hash="!", bandcamp_fan_url=FAN_URL)
        s.add(user)
        await s.flush()
        scan = await create_collection_scan(s, user)
        sid = scan.id

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(engine, "curate", fake_curate)
        await advance_scan(
            sessionmaker_, FakeFetcher({FAN_URL: fan_html}), sid,
            collection_client=client, follows_client=FakeFollowsClient(),
            supporters_client=FakeSupportersClient(), max_depth=0, max_requests_per_scan=50,
            slice_entries=1, curate_each_slice=True,
        )
    return calls


async def test_interim_curation_waits_for_a_partial_own_collection(sessionmaker_) -> None:  # noqa: ANN001
    """Curating early is the whole point — but not before the owner's own
    collection is read. Every exclusion (owned / wishlisted / followed) comes from
    that crawl, so showing someone records they already own is worse than showing
    them nothing yet."""
    calls = await _curate_calls_for(
        sessionmaker_, "partial", _fan_html_with_more_pages(), EndlessCollectionClient()
    )
    assert calls == []  # still paginating → exclusions incomplete → held back


async def test_interim_curation_runs_once_the_collection_is_read(sessionmaker_) -> None:  # noqa: ANN001
    # Fully read in one visit → the feed can safely fill in mid-crawl.
    calls = await _curate_calls_for(sessionmaker_, "complete", FAN_HTML, FakeCollectionClient())
    assert len(calls) == 1


async def test_interim_curation_resolves_seeds_first(sessionmaker_) -> None:  # noqa: ANN001
    """A custom scan scores from its *resolved* seed. Seed resolution used to
    happen only at finalize, so every mid-crawl curate found no seed, no
    taste-neighbours, and returned nothing — the live feed was a no-op for exactly
    the scans it was built for."""
    async with sessionmaker_() as s:
        fan = Fan(bandcamp_fan_id=1, username="me", url="https://bandcamp.com/me")
        s.add(fan)
        await s.flush()
        user = User(username="me", password_hash="!", fan_id=fan.id)
        s.add(user)
        await s.commit()
        scan = await create_scan(s, user.id, "dig", [ALBUM_URL])
        scan_id = scan.id

    await advance_scan(
        sessionmaker_, FakeFetcher({ALBUM_URL: ALBUM_HTML}), scan_id,
        supporters_client=FakeSupportersClient(), max_depth=0, max_requests_per_scan=50,
        curate_each_slice=True,
    )

    async with sessionmaker_() as s:
        seed = (await s.execute(select(ScanSeed).where(ScanSeed.scan_id == scan_id))).scalar_one()
        # Resolved mid-crawl, not left for finalize — otherwise curation scores nothing.
        assert seed.resolved_album_id is not None


async def test_a_timed_out_entry_keeps_the_scan_from_finalizing(sessionmaker_) -> None:  # noqa: ANN001
    """The bug this guards: `advance_scan` reports "more work?" from
    `pending_count`, which sees PENDING only. A timed-out entry left IN_PROGRESS is
    invisible to it, so the scan finalizes, the chain stops, and nothing ever calls
    `claim_next` again to trigger stale reclaim — the entry isn't deferred, it's
    abandoned, and the scan reports done without it."""
    import asyncio as _asyncio

    class Hangs:
        async def fetch(self, request):  # noqa: ANN001,ANN202
            await _asyncio.sleep(30)

    async with sessionmaker_() as s:
        fan = Fan(bandcamp_fan_id=1, username="me", url="https://bandcamp.com/me")
        s.add(fan)
        await s.flush()
        user = User(username="me", password_hash="!", fan_id=fan.id)
        s.add(user)
        await s.commit()
        scan = await create_scan(s, user.id, "dig", [ALBUM_URL])
        scan_id = scan.id

    more = await advance_scan(
        sessionmaker_, Hangs(), scan_id, supporters_client=FakeSupportersClient(),
        max_depth=0, max_requests_per_scan=50, entry_seconds=0.2,
    )

    assert more is True  # the scan must NOT finalize on unfinished work
    async with sessionmaker_() as s:
        entry = (await s.execute(select(CrawlFrontier).where(
            CrawlFrontier.scan_id == scan_id))).scalar_one()
        assert entry.status == CrawlStatus.PENDING
        assert await frontier.pending_count(s, scan_id=scan_id) == 1  # visible as work
