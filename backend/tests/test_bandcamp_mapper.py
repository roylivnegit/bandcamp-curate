from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.bandcamp.mapper import (
    ingest_album,
    ingest_album_supporters,
    ingest_fan_collection,
    ingest_track_page,
    ingest_track_supporters,
)
from app.bandcamp.parse import (
    FanCollection,
    ParsedBand,
    ParsedFan,
    ParsedItem,
    parse_album_page,
    parse_album_supporters,
    parse_fan_page,
    parse_track_page,
)
from app.db.base import Base
from app.db.models import (
    Album,
    AlbumSupporter,
    AlbumTag,
    Band,
    BandTag,
    Fan,
    FanItem,
    Follow,
    Tag,
    Track,
    TrackSupporter,
    TrackTag,
)

FIXTURE = Path(__file__).parent / "fixtures" / "fan_page.html"
ALBUM_FIXTURE = Path(__file__).parent / "fixtures" / "album_page.html"
TRACK_FIXTURE = Path(__file__).parent / "fixtures" / "track_page.html"


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

    # A fan-collection item's own art_id (not the parent album's) lands on the
    # item's row — parsed straight off Bandcamp's item_art_id, not derived.
    owned_album = (
        await session.execute(select(Album).where(Album.bandcamp_id == 4255072328))
    ).scalar_one()
    assert owned_album.art_id == 435129856
    owned_track = (await session.execute(select(Track))).scalar_one()
    assert owned_track.art_id == 3864705594


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


def _fan_html_with_wishlist() -> str:
    import html as _html
    import json as _json

    def item(iid, title):
        return {"item_id": iid, "item_type": "album", "band_id": iid * 10,
                "band_name": f"Band{iid}", "item_title": title,
                "item_url": f"https://b{iid}.bandcamp.com/album/x",
                "url_hints": {"subdomain": f"b{iid}"}}

    blob = {
        "fan_data": {"fan_id": 555, "username": "me", "name": "Me",
                     "trackpipe_url": "https://bandcamp.com/me"},
        "item_cache": {
            "collection": {"a": item(1, "Owned")},
            "wishlist": {"b": item(2, "Wanted"), "c": item(3, "AlsoWanted")},
            "following_bands": {},
        },
        "collection_data": {"item_count": 1, "last_token": None},
        "wishlist_data": {"item_count": 2, "last_token": None},
    }
    enc = _html.escape(_json.dumps(blob), quote=True)
    return f'<div id="pagedata" data-blob="{enc}"></div>'


async def test_wishlist_ingested_as_flagged_fan_items(session: AsyncSession) -> None:
    fc = parse_fan_page(_fan_html_with_wishlist())
    assert len(fc.items) == 1 and len(fc.wishlist) == 2

    counts = await ingest_fan_collection(session, fc, is_me=True)
    assert counts.fan_items == 1 and counts.wishlist_items == 2

    owned = (await session.execute(
        select(func.count()).select_from(FanItem).where(FanItem.is_wishlist.is_(False))
    )).scalar_one()
    wished = (await session.execute(
        select(func.count()).select_from(FanItem).where(FanItem.is_wishlist.is_(True))
    )).scalar_one()
    assert owned == 1 and wished == 2


async def test_wishlist_skipped_for_other_fans(session: AsyncSession) -> None:
    fc = parse_fan_page(_fan_html_with_wishlist())
    counts = await ingest_fan_collection(session, fc, is_me=False)
    assert counts.wishlist_items == 0  # only ingested for is_me
    wished = (await session.execute(
        select(func.count()).select_from(FanItem).where(FanItem.is_wishlist.is_(True))
    )).scalar_one()
    assert wished == 0


async def test_purchasing_a_wishlisted_item_flips_it_to_owned(session: AsyncSession) -> None:
    # `uq_fan_item` is on (fan_id, item_type, album_id, track_id) only — not
    # `is_wishlist` — so a later re-crawl observing the same album as owned
    # must update the existing row rather than being treated as a no-op dup.
    fan = ParsedFan(fan_id=555, username="me", name="Me", url="https://bandcamp.com/me")
    band = ParsedBand(bandcamp_id=20, name="Band2", url="https://b2.bandcamp.com")
    item = ParsedItem(
        item_id=2, item_type="album", band=band, title="Wanted",
        url="https://b2.bandcamp.com/album/x",
    )

    await ingest_fan_collection(session, FanCollection(fan=fan, wishlist=[item]), is_me=True)
    assert await _count(session, FanItem) == 1
    wished = (await session.execute(
        select(FanItem).where(FanItem.is_wishlist.is_(True))
    )).scalar_one()
    assert wished.is_wishlist is True

    # Same album, now actually owned.
    await ingest_fan_collection(session, FanCollection(fan=fan, items=[item]), is_me=True)

    assert await _count(session, FanItem) == 1  # still one edge, not a duplicate
    owned = (await session.execute(select(FanItem))).scalar_one()
    assert owned.is_wishlist is False


async def test_ingest_album_populates_graph(session: AsyncSession) -> None:
    pa = parse_album_page(ALBUM_FIXTURE.read_text())
    counts = await ingest_album(session, pa)

    assert await _count(session, Album) == 1
    assert await _count(session, Band) == 1
    assert await _count(session, Track) == 1
    assert await _count(session, Tag) == 4
    assert await _count(session, AlbumTag) == 4
    assert counts.tracks == 1 and counts.tags == 4

    album = (await session.execute(select(Album))).scalar_one()
    assert album.bandcamp_id == 4255072328
    assert album.title == "Panchito"
    assert album.band_id is not None
    assert album.art_id == 435129856

    track = (await session.execute(select(Track))).scalar_one()
    assert track.track_num == 1
    assert track.duration == 486.761


async def test_ingest_album_tags_band_and_tracks(session: AsyncSession) -> None:
    pa = parse_album_page(ALBUM_FIXTURE.read_text())  # 4 tags, 1 track
    await ingest_album(session, pa)
    assert await _count(session, AlbumTag) == 4
    assert await _count(session, BandTag) == 4          # band gets all 4 tags
    assert await _count(session, TrackTag) == 4          # 1 track × 4 tags

    # Idempotent — no duplicate band/track tag rows on re-ingest.
    await ingest_album(session, pa)
    assert await _count(session, BandTag) == 4
    assert await _count(session, TrackTag) == 4


async def test_ingest_album_is_idempotent(session: AsyncSession) -> None:
    pa = parse_album_page(ALBUM_FIXTURE.read_text())
    await ingest_album(session, pa)
    second = await ingest_album(session, pa)
    assert second.tracks == 0 and second.tags == 0
    assert await _count(session, Track) == 1
    assert await _count(session, AlbumTag) == 4


async def test_ingest_album_supporters(session: AsyncSession) -> None:
    pa = parse_album_page(ALBUM_FIXTURE.read_text())
    await ingest_album(session, pa)
    album = (await session.execute(select(Album))).scalar_one()

    sup = parse_album_supporters(ALBUM_FIXTURE.read_text())
    counts = await ingest_album_supporters(session, album, sup)

    assert counts.supporters == 3 and counts.fans == 3
    assert await _count(session, AlbumSupporter) == 3
    assert await _count(session, Fan) == 3

    guron = (
        await session.execute(select(Fan).where(Fan.username == "guron"))
    ).scalar_one()
    assert guron.bandcamp_fan_id == 9985893

    # Idempotent re-ingest creates nothing new.
    second = await ingest_album_supporters(session, album, sup)
    assert second.supporters == 0 and second.fans == 0
    assert await _count(session, AlbumSupporter) == 3


async def test_supporter_reuses_existing_fan(session: AsyncSession) -> None:
    # guron already exists (as "me") from a fan-collection ingest.
    fc = parse_fan_page(FIXTURE.read_text())
    await ingest_fan_collection(session, fc, is_me=True)
    fans_before = await _count(session, Fan)

    pa = parse_album_page(ALBUM_FIXTURE.read_text())
    await ingest_album(session, pa)
    album = (
        await session.execute(select(Album).where(Album.bandcamp_id == 4255072328))
    ).scalar_one()
    sup = parse_album_supporters(ALBUM_FIXTURE.read_text())
    counts = await ingest_album_supporters(session, album, sup)

    # guron matched by fan_id → only the 2 new supporters became new fans.
    assert counts.fans == 2
    assert await _count(session, Fan) == fans_before + 2
    me = (await session.execute(select(Fan).where(Fan.bandcamp_fan_id == 9985893))).scalar_one()
    assert me.is_me is True  # existing "me" fan reused, not duplicated


async def test_ingest_track_page_populates_graph(session: AsyncSession) -> None:
    pt = parse_track_page(TRACK_FIXTURE.read_text())
    counts = await ingest_track_page(session, pt)

    assert await _count(session, Track) == 1
    assert await _count(session, Band) == 1
    # A stub Album is created for the track's parent (id/url only, not crawled).
    assert await _count(session, Album) == 1
    assert await _count(session, AlbumTag) == 0  # never written for a stub album
    assert counts.tags == 7

    track = (await session.execute(select(Track))).scalar_one()
    assert track.bandcamp_id == 2231778447
    assert track.title == "Return Of The King (Original Mix)"
    assert track.band_id is not None
    assert track.album_id is not None
    assert track.art_id == 3864705594

    album = (await session.execute(select(Album))).scalar_one()
    assert album.bandcamp_id == 1818018872
    assert album.title is None  # stub — only id/url known


async def test_ingest_track_page_tags_band_and_track(session: AsyncSession) -> None:
    pt = parse_track_page(TRACK_FIXTURE.read_text())  # 7 tags
    await ingest_track_page(session, pt)
    assert await _count(session, TrackTag) == 7
    assert await _count(session, BandTag) == 7

    # Idempotent re-ingest.
    second = await ingest_track_page(session, pt)
    assert second.tags == 0
    assert await _count(session, TrackTag) == 7
    assert await _count(session, BandTag) == 7


async def test_ingest_track_page_without_album(session: AsyncSession) -> None:
    # A standalone single with no parent album.
    pt = parse_track_page(TRACK_FIXTURE.read_text())
    pt.album_id = None
    pt.album_url = None
    await ingest_track_page(session, pt)
    assert await _count(session, Album) == 0
    track = (await session.execute(select(Track))).scalar_one()
    assert track.album_id is None


async def test_ingest_track_supporters(session: AsyncSession) -> None:
    pt = parse_track_page(TRACK_FIXTURE.read_text())
    await ingest_track_page(session, pt)
    track = (await session.execute(select(Track))).scalar_one()

    sup = parse_album_supporters(TRACK_FIXTURE.read_text())
    assert sup.tralbum_type == "t"
    counts = await ingest_track_supporters(session, track, sup)

    assert counts.supporters == 3 and counts.fans == 3
    assert await _count(session, TrackSupporter) == 3
    assert await _count(session, AlbumSupporter) == 0  # never an album edge
    assert await _count(session, Fan) == 3

    guron = (await session.execute(select(Fan).where(Fan.username == "guron"))).scalar_one()
    assert guron.bandcamp_fan_id == 9985893

    # Idempotent re-ingest creates nothing new.
    second = await ingest_track_supporters(session, track, sup)
    assert second.supporters == 0 and second.fans == 0
    assert await _count(session, TrackSupporter) == 3
