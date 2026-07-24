from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.bandcamp.mapper import ingest_fan_collection
from app.bandcamp.parse import parse_fan_page
from app.db.base import Base
from app.db.models import Album, Band, Fan, FanItem, Follow, Track

FIXTURE = Path(__file__).parent / "fixtures" / "fan_page.html"


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def _count(session: AsyncSession, model) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def test_ingest_populates_graph(session: AsyncSession) -> None:
    fc = parse_fan_page(FIXTURE.read_text())
    counts = await ingest_fan_collection(session, fc, is_me=True)

    assert await _count(session, Fan) == 1
    assert await _count(session, FanItem) == 2  # one album + one track owned
    assert counts.fan_items == 2

    # is_me → follows recorded (fixture has 2 followed bands).
    assert await _count(session, Follow) == 2
    assert counts.follows == 2

    me = (await session.execute(select(Fan).where(Fan.is_me.is_(True)))).scalar_one()
    assert me.username == "guron"

    # The track's parent album should have been created too.
    assert await _count(session, Album) >= 1
    assert await _count(session, Track) == 1


async def test_ingest_is_idempotent(session: AsyncSession) -> None:
    fc = parse_fan_page(FIXTURE.read_text())
    await ingest_fan_collection(session, fc, is_me=True)
    bands_after_first = await _count(session, Band)

    second = await ingest_fan_collection(session, fc, is_me=True)
    assert second.fan_items == 0  # nothing new created
    assert second.follows == 0
    assert await _count(session, FanItem) == 2
    assert await _count(session, Band) == bands_after_first


async def test_other_fan_does_not_create_follows(session: AsyncSession) -> None:
    fc = parse_fan_page(FIXTURE.read_text())
    await ingest_fan_collection(session, fc, is_me=False)
    assert await _count(session, Follow) == 0  # follows only for is_me
