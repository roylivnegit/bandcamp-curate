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
from app.crawl import runner
from app.crawl.scan_service import (
    claim_queued_scans,
    create_collection_scan,
    create_scan,
    parse_seed_url,
    run_scan,
)
from app.db.base import Base
from app.db.models import Fan, FanItem, Scan, ScanSeed, User
from app.db.session import get_session
from app.enums import ScanKind, ScanStatus
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
        supporters_client=FakeSupportersClient(), max_depth=1, max_requests=50,
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
        supporters_client=FakeSupportersClient(), max_depth=1, max_requests=50,
    )
    assert seen["seed_fan_id"] == fan_id


async def test_collection_scan_picks_up_the_fan_it_just_created(sessionmaker_) -> None:  # noqa: ANN001
    # A first-ever collection scan has no user.fan_id when it starts — the depth-0
    # crawl creates it. The drain that follows must use that fresh id, not None.
    async with sessionmaker_() as s:
        user = User(username="guron", password_hash="!", bandcamp_fan_url=FAN_URL)
        s.add(user)
        await s.flush()
        scan = await create_collection_scan(s, user)
        user_id, scan_id = user.id, scan.id
        assert user.fan_id is None

    seen: dict = {}
    real_run = runner.run_until_empty

    async def spy(*a, **kw):  # noqa: ANN002,ANN003,ANN202
        seen.update(kw)
        return await real_run(*a, **kw)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(runner, "run_until_empty", spy)
        await _run_collection_scan(sessionmaker_, user_id, scan_id)

    async with sessionmaker_() as s:
        crawled_fan_id = (await s.get(User, user_id)).fan_id
    assert crawled_fan_id is not None
    assert seen["seed_fan_id"] == crawled_fan_id


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
        supporters_client=FakeSupportersClient(), max_depth=1, max_requests=50,
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
    """The collection/wishlist XHRs return nothing extra beyond the embedded page."""

    async def iter_items(self, *a, **kw):  # noqa: ANN002,ANN003,ANN202
        return
        yield  # pragma: no cover


class FakeFollowsClient:
    async def iter_bands(self, *a, **kw):  # noqa: ANN002,ANN003,ANN202
        return
        yield  # pragma: no cover


async def _run_collection_scan(sessionmaker_, user_id: int, scan_id: int):  # noqa: ANN001,ANN202
    fetcher = FakeFetcher({FAN_URL: FAN_HTML, "/album/": ALBUM_HTML})
    return await run_scan(
        sessionmaker_, fetcher, scan_id,
        collection_client=FakeCollectionClient(), follows_client=FakeFollowsClient(),
        supporters_client=FakeSupportersClient(), max_depth=1, max_requests=50,
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
