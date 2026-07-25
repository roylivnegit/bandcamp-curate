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

from app.crawl.scan_service import (
    claim_queued_scans,
    create_scan,
    parse_seed_url,
    run_scan,
)
from app.db.base import Base
from app.db.models import Fan, Scan, ScanSeed
from app.db.session import get_session
from app.enums import ScanKind, ScanStatus
from app.main import app

FIXTURES = Path(__file__).parent / "fixtures"
ALBUM_HTML = (FIXTURES / "album_page.html").read_text()
ALBUM_URL = "https://cerebro-spinal.bandcamp.com/album/panchito"


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

    async def _override() -> AsyncIterator[AsyncSession]:
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = _override
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
    r = await post("n", ["https://x.bandcamp.com/track/t"])        # track not supported yet
    assert r.status_code == 400 and "track" in r.json()["detail"]
    assert (await post("n", ["https://google.com"])).status_code == 400  # not a release URL


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
        s.add_all([
            Scan(name="a", kind=str(ScanKind.CUSTOM), status=str(ScanStatus.QUEUED)),
            Scan(name="b", kind=str(ScanKind.CUSTOM), status=str(ScanStatus.DONE)),
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
        # curation needs the is_me fan as the shared exclusion base (a prior
        # collection crawl would have created it).
        s.add(Fan(bandcamp_fan_id=1, username="me", url="https://bandcamp.com/me", is_me=True))
        await s.commit()
        scan = await create_scan(s, "Panchito dig", [ALBUM_URL])
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
