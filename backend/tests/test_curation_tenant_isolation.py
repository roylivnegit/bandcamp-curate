"""Regression coverage for the cross-tenant leaks CLAUDE.md documents as fixed
(M8: `follows` scoped per-fan, `blacklist`/`likes` scoped per-user) — pinning
that `build_exclusions` keeps two users' preferences apart so a future edit
can't silently reintroduce the leak with nothing red to catch it.

The Bandcamp catalog (bands/albums) is deliberately GLOBAL and shared between
the two users here, matching the real schema: two tenants routinely see the
same band/album rows, and isolation has to come from the exclusion query being
scoped by `fan_id`/`user_id`, not from the catalog rows themselves differing.
"""

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.curation.engine import build_exclusions
from app.db.base import Base
from app.db.models import Band, Blacklist, Fan, Follow, User
from app.enums import BandKind, TargetType


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


async def _build_two_tenants(s: AsyncSession):
    """Two users, each with their own Fan, sharing the same global Band catalog.

    User A follows Band X (a `follows` row, fan-scoped) and blacklists Band Y
    (a `blacklist` row, user-scoped). User B does neither.
    """
    fan_a = Fan(bandcamp_fan_id=1, username="a", url="https://bandcamp.com/a", is_me=True)
    fan_b = Fan(bandcamp_fan_id=2, username="b", url="https://bandcamp.com/b", is_me=True)
    band_x = Band(bandcamp_id=1, name="BandX", kind=BandKind.ARTIST)
    band_y = Band(bandcamp_id=2, name="BandY", kind=BandKind.ARTIST)
    s.add_all([fan_a, fan_b, band_x, band_y])
    await s.flush()

    user_a = User(username="a", password_hash="!", fan_id=fan_a.id)
    user_b = User(username="b", password_hash="!", fan_id=fan_b.id)
    s.add_all([user_a, user_b])
    await s.flush()

    s.add_all([
        Follow(fan_id=fan_a.id, band_id=band_x.id, target_type=TargetType.ARTIST),
        Blacklist(user_id=user_a.id, target_type=TargetType.ARTIST, band_id=band_y.id),
    ])
    await s.commit()
    return fan_a, user_a, fan_b, user_b, band_x, band_y


async def test_follow_and_blacklist_do_not_leak_to_another_tenant(session: AsyncSession) -> None:
    fan_a, user_a, fan_b, user_b, band_x, band_y = await _build_two_tenants(session)

    excl_a = await build_exclusions(session, fan_a, user_a)
    excl_b = await build_exclusions(session, fan_b, user_b)

    # A's own follow + blacklist do apply to A.
    assert band_x.id in excl_a.band_ids
    assert band_y.id in excl_a.band_ids

    # Neither leaks into B's exclusions, even though both share the same
    # global Band rows.
    assert band_x.id not in excl_b.band_ids
    assert band_y.id not in excl_b.band_ids
