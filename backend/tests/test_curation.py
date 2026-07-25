from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.curation.engine import (
    compute_recommendations,
    curate,
    ensure_collection_scan,
    get_me,
)
from app.db.base import Base
from app.db.models import (
    Album,
    AlbumSupporter,
    AlbumTag,
    Band,
    Blacklist,
    Fan,
    FanItem,
    Follow,
    Like,
    Recommendation,
    Tag,
    Track,
)
from app.enums import BandKind, ItemType, TargetType


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


async def _recs(s: AsyncSession, **kw):
    """Compute the collection scan's recommendations (the default feed)."""
    scan = await ensure_collection_scan(s)
    return await compute_recommendations(s, scan, **kw)


async def _build_graph(s: AsyncSession) -> None:
    """A small world:
      me owns A1(B1, tags rock,jazz) + track T1; wishlists A2; follows B3.
      F2 & F3 both SUPPORT my A1 → both are collection-scan neighbours.
      F2 owns A1, A2, A3(B3), A4(B4, tag rock), T2.
      F3 owns A4, A5(B5).
    Expected recs: A4 (co=2, tag rock matched) > A5 (co=1); T2 (co=1).
    A1 excluded (owned), A2 (wishlist), A3 (band followed).
    """
    me = Fan(bandcamp_fan_id=1, username="me", url="https://bandcamp.com/me", is_me=True)
    f2 = Fan(bandcamp_fan_id=2, username="f2", url="https://bandcamp.com/f2")
    f3 = Fan(bandcamp_fan_id=3, username="f3", url="https://bandcamp.com/f3")
    bands = {n: Band(bandcamp_id=n, name=f"B{n}", kind=BandKind.ARTIST) for n in range(1, 6)}
    s.add_all([me, f2, f3, *bands.values()])
    await s.flush()

    def album(aid, bandnum):
        a = Album(bandcamp_id=aid, title=f"A{aid}", band_id=bands[bandnum].id)
        s.add(a)
        return a

    a1, a2, a3, a4, a5 = album(1, 1), album(2, 2), album(3, 3), album(4, 4), album(5, 5)
    t1 = Track(bandcamp_id=101, title="T1", band_id=bands[1].id)
    t2 = Track(bandcamp_id=102, title="T2", band_id=bands[2].id)
    s.add_all([t1, t2])
    await s.flush()

    rock = Tag(name="rock")
    jazz = Tag(name="jazz")
    s.add_all([rock, jazz])
    await s.flush()
    # my A1 → rock, jazz ; candidate A4 → rock (matches my profile)
    s.add_all([
        AlbumTag(album_id=a1.id, tag_id=rock.id),
        AlbumTag(album_id=a1.id, tag_id=jazz.id),
        AlbumTag(album_id=a4.id, tag_id=rock.id),
    ])

    # ownership edges
    s.add_all([
        FanItem(fan_id=me.id, item_type=ItemType.ALBUM, album_id=a1.id),
        FanItem(fan_id=me.id, item_type=ItemType.TRACK, track_id=t1.id),
        FanItem(fan_id=me.id, item_type=ItemType.ALBUM, album_id=a2.id, is_wishlist=True),
        FanItem(fan_id=f2.id, item_type=ItemType.ALBUM, album_id=a1.id),
        FanItem(fan_id=f2.id, item_type=ItemType.ALBUM, album_id=a2.id),
        FanItem(fan_id=f2.id, item_type=ItemType.ALBUM, album_id=a3.id),
        FanItem(fan_id=f2.id, item_type=ItemType.ALBUM, album_id=a4.id),
        FanItem(fan_id=f2.id, item_type=ItemType.TRACK, track_id=t2.id),
        FanItem(fan_id=f3.id, item_type=ItemType.ALBUM, album_id=a4.id),
        FanItem(fan_id=f3.id, item_type=ItemType.ALBUM, album_id=a5.id),
        # F2 & F3 support my A1 → they're neighbours of the collection scan.
        AlbumSupporter(album_id=a1.id, fan_id=f2.id),
        AlbumSupporter(album_id=a1.id, fan_id=f3.id),
    ])
    s.add(Follow(band_id=bands[3].id, target_type=TargetType.ARTIST))  # I follow B3
    await s.commit()


async def test_recommendations_exclude_and_rank(session: AsyncSession) -> None:
    await _build_graph(session)
    scored = await _recs(session)

    albums = [s for s in scored if s.album_id is not None]
    rec_album_bcids = {}
    for sc in albums:
        a = (await session.execute(select(Album).where(Album.id == sc.album_id))).scalar_one()
        rec_album_bcids[a.bandcamp_id] = sc

    # A1 (owned), A2 (wishlisted), A3 (followed band) are all excluded.
    assert set(rec_album_bcids) == {4, 5}
    # A4 has 2 co-owners (F2,F3) + a matched tag; A5 has 1 → A4 ranks first.
    assert scored[0].album_id == rec_album_bcids[4].album_id
    assert rec_album_bcids[4].reasons["co_owners"] == 2
    assert "rock" in rec_album_bcids[4].reasons["matched_tags"]
    assert rec_album_bcids[4].score > rec_album_bcids[5].score

    # Track T2 (owned by F2) is a candidate; my own T1 is excluded.
    tracks = [s for s in scored if s.track_id is not None]
    assert len(tracks) == 1 and tracks[0].reasons["co_owners"] == 1


async def test_one_recommendation_per_band(session: AsyncSession) -> None:
    await _build_graph(session)
    # Give B4 a second candidate album (a6), owned by two neighbours → higher score.
    b4 = (await session.execute(select(Band).where(Band.bandcamp_id == 5))).scalar_one()
    a6 = Album(bandcamp_id=6, title="A6 same band as A5", band_id=b4.id)
    session.add(a6)
    await session.flush()
    f2 = (await session.execute(select(Fan).where(Fan.username == "f2"))).scalar_one()
    f3 = (await session.execute(select(Fan).where(Fan.username == "f3"))).scalar_one()
    session.add_all([
        FanItem(fan_id=f2.id, item_type=ItemType.ALBUM, album_id=a6.id),
        FanItem(fan_id=f3.id, item_type=ItemType.ALBUM, album_id=a6.id),
    ])
    await session.commit()

    deduped = await _recs(session, one_per_band=True)
    band_ids = [s.band_id for s in deduped]
    assert len(band_ids) == len(set(band_ids))  # no band appears twice
    # For band 5, the 2-owner album a6 wins over the 1-owner a5.
    b5_rec = next(s for s in deduped if s.band_id == b4.id)
    assert b5_rec.album_id == a6.id

    full = await _recs(session, one_per_band=False)
    assert len(full) > len(deduped)  # dedup actually removed something


async def test_curate_persists_and_is_idempotent(session: AsyncSession) -> None:
    await _build_graph(session)
    scored = await curate(session)
    assert await _count(session, Recommendation) == len(scored)
    # Re-running replaces, doesn't duplicate.
    again = await curate(session)
    assert await _count(session, Recommendation) == len(again) == len(scored)


async def test_blacklist_excludes_candidate(session: AsyncSession) -> None:
    await _build_graph(session)
    a4 = (await session.execute(select(Album).where(Album.bandcamp_id == 4))).scalar_one()
    session.add(Blacklist(target_type=str(TargetType.ALBUM), album_id=a4.id, active=True))
    await session.commit()

    scored = await _recs(session)
    rec_album_ids = {s.album_id for s in scored if s.album_id}
    assert a4.id not in rec_album_ids  # blacklisted → gone


async def test_follow_by_label_url_excludes_albums_on_that_page(
    session: AsyncSession,
) -> None:
    # Follow a LABEL (band 3, url label.bandcamp.com). A neighbour owns an album on
    # that label's page whose stored band is a *different* id (the artist). band_id
    # matching would miss it; host matching must catch it.
    await _build_graph(session)
    label = (await session.execute(select(Band).where(Band.bandcamp_id == 3))).scalar_one()
    label.url = "https://label.bandcamp.com"
    artist = Band(bandcamp_id=99, name="Artist On Label", kind=BandKind.ARTIST)
    session.add(artist)
    await session.flush()
    # album on the label's page, band = the artist (not followed by id)
    a = Album(bandcamp_id=900, title="On The Label",
              url="https://label.bandcamp.com/album/x", band_id=artist.id)
    session.add(a)
    await session.flush()
    f2 = (await session.execute(select(Fan).where(Fan.username == "f2"))).scalar_one()
    session.add(FanItem(fan_id=f2.id, item_type=ItemType.ALBUM, album_id=a.id))
    await session.commit()

    scored = await _recs(session)
    rec_album_ids = {s.album_id for s in scored if s.album_id}
    assert a.id not in rec_album_ids  # excluded via followed label's URL host


async def test_seed_tag_provenance_and_exclusion(session: AsyncSession) -> None:
    # me owns A1 (tagged rock,jazz). f2 supports A1 (from _build_graph) and owns A4.
    # So A4's seed provenance = {rock, jazz}. Excluding "rock" drops A4.
    await _build_graph(session)
    me = (await session.execute(select(Fan).where(Fan.is_me.is_(True)))).scalar_one()
    a4 = (await session.execute(select(Album).where(Album.bandcamp_id == 4))).scalar_one()

    scored = await _recs(session)
    a4_rec = next(s for s in scored if s.album_id == a4.id)
    assert set(a4_rec.reasons["seed_tags"]) == {"rock", "jazz"}  # provenance recorded

    filtered = await _recs(session, exclude_seed_tags={"rock"})
    assert a4.id not in {s.album_id for s in filtered}  # generated-from-rock → gone

    _ = me  # (me is the seed; used implicitly by the engine)


async def test_seed_tags_lists_my_album_genres(session: AsyncSession) -> None:
    from app.curation.engine import seed_tags

    await _build_graph(session)  # my A1 is tagged rock + jazz
    genres = dict(await seed_tags(session))
    assert genres.get("rock") == 1 and genres.get("jazz") == 1


async def test_liked_item_excludes_its_band(session: AsyncSession) -> None:
    await _build_graph(session)
    a4 = (await session.execute(select(Album).where(Album.bandcamp_id == 4))).scalar_one()
    # A sibling album on the SAME band as a4, owned by a neighbour.
    a7 = Album(bandcamp_id=7, title="Sibling", band_id=a4.band_id)
    session.add(a7)
    await session.flush()
    f3 = (await session.execute(select(Fan).where(Fan.username == "f3"))).scalar_one()
    session.add(FanItem(fan_id=f3.id, item_type=ItemType.ALBUM, album_id=a7.id))
    await session.commit()

    before = {s.album_id for s in await _recs(session)}
    assert a4.id in before  # (a7 shares a4's band → deduped to one, but band present)

    # Liking a4 excludes its whole band → neither a4 nor its sibling a7 appear.
    session.add(Like(item_type=str(ItemType.ALBUM), album_id=a4.id))
    await session.commit()
    after = {s.album_id for s in await _recs(session)}
    assert a4.id not in after and a7.id not in after


async def test_get_me_requires_seed(session: AsyncSession) -> None:
    import pytest

    with pytest.raises(ValueError, match="no is_me fan"):
        await get_me(session)


async def _count(session: AsyncSession, model) -> int:
    from sqlalchemy import func

    return (await session.execute(select(func.count()).select_from(model))).scalar_one()
