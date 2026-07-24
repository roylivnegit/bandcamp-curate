"""Persist parsed Bandcamp records into the graph (idempotent upserts).

Entities are keyed by their Bandcamp id, so re-ingesting the same fan/collection is
safe (get-or-create + light enrichment). Follows are recorded only for your own
collection (`is_me=True`), since the `follows` table means "artists/labels I follow".
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bandcamp.parse import FanCollection, ParsedBand, ParsedItem
from app.db.models import Album, Band, Fan, FanItem, Follow, Track
from app.enums import BandKind, ItemType, TargetType


@dataclass(slots=True)
class IngestCounts:
    fan_items: int = 0  # new ownership edges created this ingest
    follows: int = 0  # new follows created this ingest (is_me only)


async def get_or_create_band(session: AsyncSession, pb: ParsedBand) -> Band | None:
    if pb.bandcamp_id is None:
        return None
    band = (
        await session.execute(select(Band).where(Band.bandcamp_id == pb.bandcamp_id))
    ).scalar_one_or_none()
    if band is None:
        band = Band(bandcamp_id=pb.bandcamp_id, name=pb.name, url=pb.url, kind=BandKind.UNKNOWN)
        session.add(band)
        await session.flush()
        return band
    # Enrich missing fields only (never clobber existing data).
    if pb.name and not band.name:
        band.name = pb.name
    if pb.url and not band.url:
        band.url = pb.url
    return band


async def get_or_create_album(
    session: AsyncSession,
    *,
    bandcamp_id: int,
    url: str | None = None,
    title: str | None = None,
    band: Band | None = None,
) -> Album:
    album = (
        await session.execute(select(Album).where(Album.bandcamp_id == bandcamp_id))
    ).scalar_one_or_none()
    if album is None:
        album = Album(
            bandcamp_id=bandcamp_id,
            url=url,
            title=title,
            band_id=band.id if band else None,
        )
        session.add(album)
        await session.flush()
        return album
    if url and not album.url:
        album.url = url
    if title and not album.title:
        album.title = title
    if band and not album.band_id:
        album.band_id = band.id
    return album


async def get_or_create_track(
    session: AsyncSession,
    *,
    bandcamp_id: int,
    url: str | None = None,
    title: str | None = None,
    band: Band | None = None,
    album: Album | None = None,
) -> Track:
    track = (
        await session.execute(select(Track).where(Track.bandcamp_id == bandcamp_id))
    ).scalar_one_or_none()
    if track is None:
        track = Track(
            bandcamp_id=bandcamp_id,
            url=url,
            title=title,
            band_id=band.id if band else None,
            album_id=album.id if album else None,
        )
        session.add(track)
        await session.flush()
        return track
    if url and not track.url:
        track.url = url
    if title and not track.title:
        track.title = title
    if band and not track.band_id:
        track.band_id = band.id
    if album and not track.album_id:
        track.album_id = album.id
    return track


async def get_or_create_fan(session: AsyncSession, fan_id: int, username: str, *, name: str | None,
                            url: str | None, is_me: bool) -> Fan:
    fan = (
        await session.execute(select(Fan).where(Fan.bandcamp_fan_id == fan_id))
    ).scalar_one_or_none()
    if fan is None:
        fan = Fan(
            bandcamp_fan_id=fan_id,
            username=username,
            url=url or f"https://bandcamp.com/{username}",
            name=name,
            is_me=is_me,
        )
        session.add(fan)
        await session.flush()
        return fan
    if is_me and not fan.is_me:
        fan.is_me = True
    if name and not fan.name:
        fan.name = name
    return fan


async def _add_fan_item(session: AsyncSession, fan: Fan, item_type: ItemType,
                        album: Album | None = None, track: Track | None = None) -> bool:
    """Insert a fan↔item edge if absent. Returns True if a new row was created."""
    stmt = select(FanItem).where(
        FanItem.fan_id == fan.id,
        FanItem.item_type == item_type,
        FanItem.album_id == (album.id if album else None),
        FanItem.track_id == (track.id if track else None),
    )
    if (await session.execute(stmt)).scalar_one_or_none() is not None:
        return False
    session.add(
        FanItem(
            fan_id=fan.id,
            item_type=item_type,
            album_id=album.id if album else None,
            track_id=track.id if track else None,
        )
    )
    await session.flush()
    return True


async def ingest_item(session: AsyncSession, fan: Fan, item: ParsedItem,
                      counts: IngestCounts) -> None:
    band = await get_or_create_band(session, item.band)
    if item.item_type == "album":
        album = await get_or_create_album(
            session, bandcamp_id=item.item_id, url=item.url, title=item.title, band=band
        )
        if await _add_fan_item(session, fan, ItemType.ALBUM, album=album):
            counts.fan_items += 1
    else:
        album = None
        if item.album_id:
            album = await get_or_create_album(
                session, bandcamp_id=item.album_id, title=item.album_title, band=band
            )
        track = await get_or_create_track(
            session, bandcamp_id=item.item_id, url=item.url, title=item.title,
            band=band, album=album,
        )
        if await _add_fan_item(session, fan, ItemType.TRACK, track=track):
            counts.fan_items += 1


async def upsert_follow(session: AsyncSession, band: Band) -> bool:
    existing = (
        await session.execute(select(Follow).where(Follow.band_id == band.id))
    ).scalar_one_or_none()
    if existing is not None:
        return False
    target = band.kind if band.kind in (BandKind.ARTIST, BandKind.LABEL) else TargetType.ARTIST
    session.add(Follow(band_id=band.id, target_type=target))
    await session.flush()
    return True


async def ingest_fan_collection(
    session: AsyncSession, fc: FanCollection, *, is_me: bool = False
) -> IngestCounts:
    """Upsert a fan, their owned items, and (if is_me) their follows."""
    counts = IngestCounts()
    fan = await get_or_create_fan(
        session, fc.fan.fan_id, fc.fan.username, name=fc.fan.name, url=fc.fan.url, is_me=is_me
    )

    for item in fc.items:
        await ingest_item(session, fan, item, counts)

    if is_me:
        for pb in fc.follows:
            band = await get_or_create_band(session, pb)
            if band and await upsert_follow(session, band):
                counts.follows += 1

    await session.commit()
    return counts
