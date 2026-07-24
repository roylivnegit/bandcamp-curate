from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.curation.engine import curate
from app.db.base import Base
from app.db.models import Album, Band, Fan, FanItem, Follow, Track
from app.db.session import get_session
from app.enums import BandKind, ItemType, TargetType
from app.main import app


async def _seed(s: AsyncSession) -> None:
    # me owns A1(B1); neighbour f2 owns A1 + A2(B2) + track T2(B2).
    # follow B3 which f2 also owns (A3) → A3 excluded.
    me = Fan(bandcamp_fan_id=1, username="me", url="https://bandcamp.com/me", is_me=True)
    f2 = Fan(bandcamp_fan_id=2, username="f2", url="https://bandcamp.com/f2")
    b1, b2, b3 = (Band(bandcamp_id=n, name=f"Band{n}", kind=BandKind.ARTIST) for n in (1, 2, 3))
    s.add_all([me, f2, b1, b2, b3])
    await s.flush()
    a1 = Album(bandcamp_id=11, title="Owned", band_id=b1.id)
    a2 = Album(bandcamp_id=12, title="Recommend Me",
               url="https://b2.bandcamp.com/album/x", band_id=b2.id)
    a3 = Album(bandcamp_id=13, title="Followed", band_id=b3.id)
    t2 = Track(bandcamp_id=22, title="A Track", band_id=b2.id)
    s.add_all([a1, a2, a3, t2])
    await s.flush()
    s.add_all([
        FanItem(fan_id=me.id, item_type=ItemType.ALBUM, album_id=a1.id),
        FanItem(fan_id=f2.id, item_type=ItemType.ALBUM, album_id=a1.id),
        FanItem(fan_id=f2.id, item_type=ItemType.ALBUM, album_id=a2.id),
        FanItem(fan_id=f2.id, item_type=ItemType.ALBUM, album_id=a3.id),
        FanItem(fan_id=f2.id, item_type=ItemType.TRACK, track_id=t2.id),
        Follow(band_id=b3.id, target_type=TargetType.ARTIST),
    ])
    await s.commit()


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
        await _seed(s)
        await curate(s)  # populate recommendations

    async def _override() -> AsyncIterator[AsyncSession]:
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


async def test_stats(client: AsyncClient) -> None:
    r = await client.get("/api/stats")
    assert r.status_code == 200
    s = r.json()
    assert s["neighbours"] == 1 and s["my_owned"] == 1 and s["follows"] == 1
    assert s["request_budget"] == 100
    assert s["recommendations"] >= 1


async def test_recommendations_feed(client: AsyncClient) -> None:
    rows = (await client.get("/api/recommendations")).json()
    titles = {r["title"] for r in rows}
    assert "Recommend Me" in titles      # neighbour-owned, not mine
    assert "Owned" not in titles          # excluded: I own it
    assert "Followed" not in titles       # excluded: I follow the band
    top = rows[0]
    assert top["rank"] == 1 and top["reasons"]["co_owners"] == 1
    assert top["url"] == "https://b2.bandcamp.com/album/x"


async def test_recommendations_filter_and_paging(client: AsyncClient) -> None:
    albums = (await client.get("/api/recommendations?item_type=album")).json()
    assert all(r["item_type"] == "album" for r in albums)
    tracks = (await client.get("/api/recommendations?item_type=track")).json()
    assert all(r["item_type"] == "track" for r in tracks) and len(tracks) == 1
    # offset past the end → empty
    assert (await client.get("/api/recommendations?offset=999")).json() == []


async def test_recompute_endpoint(client: AsyncClient) -> None:
    r = await client.post("/api/recommendations/recompute")
    assert r.status_code == 200 and r.json()["computed"] >= 1


async def test_ui_served(client: AsyncClient) -> None:
    r = await client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "crate" in r.text and "/api/recommendations" in r.text
