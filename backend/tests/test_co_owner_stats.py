from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import (
    Album,
    AlbumSupporter,
    Band,
    Fan,
    FanItem,
    Recommendation,
    Scan,
    Track,
    TrackSupporter,
    User,
)
from app.enums import BandKind, ItemType, ScanKind, ScanStatus
from scripts.co_owner_stats import floor_histogram, resolve_scan, resolve_user


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


async def _build_graph(s: AsyncSession) -> tuple[User, Scan]:
    """me owns a seed album; f2/f3/f4/f5 support it (4 neighbours, no overlap
    with my other items, so weighting == raw co-owner count).

    BandX has two albums: itemA (1 co-owner) and itemB (3 co-owners) — the
    band's best-scoring item, and thus whether the band survives a floor,
    depends on itemB, not on whichever album happens to be "first". BandY has
    one album (4 co-owners). BandZ has one track (1 co-owner, no album).
    """
    me = Fan(bandcamp_fan_id=1, username="me", url="https://bandcamp.com/me", is_me=True)
    neighbours = [
        Fan(bandcamp_fan_id=n, username=f"f{n}", url=f"https://bandcamp.com/f{n}")
        for n in (2, 3, 4, 5)
    ]
    s.add_all([me, *neighbours])
    await s.flush()
    f2, f3, f4, f5 = neighbours

    user = User(username="me", password_hash="!", fan_id=me.id)
    s.add(user)
    await s.flush()
    scan = Scan(
        user_id=user.id, name="My collection", kind=str(ScanKind.COLLECTION),
        status=str(ScanStatus.DONE),
    )
    s.add(scan)
    await s.flush()

    band_seed = Band(bandcamp_id=1, name="Seed", kind=BandKind.ARTIST)
    band_x = Band(bandcamp_id=2, name="BandX", kind=BandKind.ARTIST)
    band_y = Band(bandcamp_id=3, name="BandY", kind=BandKind.ARTIST)
    band_z = Band(bandcamp_id=4, name="BandZ", kind=BandKind.ARTIST)
    s.add_all([band_seed, band_x, band_y, band_z])
    await s.flush()

    seed_album = Album(bandcamp_id=1, title="Seed", band_id=band_seed.id)
    item_a = Album(bandcamp_id=2, title="A", band_id=band_x.id)
    item_b = Album(bandcamp_id=3, title="B", band_id=band_x.id)
    item_c = Album(bandcamp_id=4, title="C", band_id=band_y.id)
    s.add_all([seed_album, item_a, item_b, item_c])
    item_d = Track(bandcamp_id=100, title="D", band_id=band_z.id)
    s.add(item_d)
    await s.flush()

    s.add_all([
        FanItem(fan_id=me.id, item_type=ItemType.ALBUM, album_id=seed_album.id),
        AlbumSupporter(album_id=seed_album.id, fan_id=f2.id),
        AlbumSupporter(album_id=seed_album.id, fan_id=f3.id),
        AlbumSupporter(album_id=seed_album.id, fan_id=f4.id),
        AlbumSupporter(album_id=seed_album.id, fan_id=f5.id),
        FanItem(fan_id=f2.id, item_type=ItemType.ALBUM, album_id=item_a.id),
        FanItem(fan_id=f2.id, item_type=ItemType.ALBUM, album_id=item_b.id),
        FanItem(fan_id=f3.id, item_type=ItemType.ALBUM, album_id=item_b.id),
        FanItem(fan_id=f4.id, item_type=ItemType.ALBUM, album_id=item_b.id),
        FanItem(fan_id=f2.id, item_type=ItemType.ALBUM, album_id=item_c.id),
        FanItem(fan_id=f3.id, item_type=ItemType.ALBUM, album_id=item_c.id),
        FanItem(fan_id=f4.id, item_type=ItemType.ALBUM, album_id=item_c.id),
        FanItem(fan_id=f5.id, item_type=ItemType.ALBUM, album_id=item_c.id),
        FanItem(fan_id=f2.id, item_type=ItemType.TRACK, track_id=item_d.id),
        TrackSupporter(track_id=item_d.id, fan_id=f2.id),
    ])
    await s.commit()
    return user, scan


async def test_floor_histogram_counts_per_item_not_per_band(session: AsyncSession) -> None:
    user, scan = await _build_graph(session)

    rows = await floor_histogram(session, user, scan, [1, 2, 3, 4, 5])
    counts = {r["floor"]: r["count"] for r in rows}

    # floor 1: BandX (via item_b), BandY, BandZ-track all survive -> 3.
    assert counts[1] == 3
    # floor 2: item_a (1 co-owner) drops but item_b (3) keeps BandX alive;
    # the track (1 co-owner) drops entirely -> BandX, BandY = 2.
    assert counts[2] == 2
    # floor 3: item_b (3) still clears the bar -> unchanged at 2.
    assert counts[3] == 2
    # floor 4: item_b (3) now fails too, only BandY (4 co-owners) survives.
    assert counts[4] == 1
    # floor 5: above every item's co-owner count -> empty, no raise.
    assert counts[5] == 0


async def test_floor_histogram_never_writes(session: AsyncSession) -> None:
    user, scan = await _build_graph(session)

    before = (await session.execute(select(func.count()).select_from(Recommendation))).scalar_one()
    scan_count_before = (await session.execute(select(func.count()).select_from(Scan))).scalar_one()

    await floor_histogram(session, user, scan, [1, 3])

    after = (await session.execute(select(func.count()).select_from(Recommendation))).scalar_one()
    scan_count_after = (await session.execute(select(func.count()).select_from(Scan))).scalar_one()
    assert after == before == 0
    assert scan_count_after == scan_count_before


async def test_resolve_scan_refuses_other_users_scan(session: AsyncSession) -> None:
    user, scan = await _build_graph(session)
    other = User(username="other", password_hash="!")
    session.add(other)
    await session.commit()

    assert await resolve_scan(session, other, scan.id) is None
    assert await resolve_scan(session, user, scan.id) is not None


async def test_resolve_scan_defaults_to_collection_scan(session: AsyncSession) -> None:
    user, scan = await _build_graph(session)
    assert (await resolve_scan(session, user, None)).id == scan.id


async def test_resolve_user_missing(session: AsyncSession) -> None:
    assert await resolve_user(session, "nobody") is None
