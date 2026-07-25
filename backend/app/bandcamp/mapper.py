"""Persist parsed Bandcamp records into the graph (idempotent upserts).

Entities are keyed by their Bandcamp id, so re-ingesting the same fan/collection is
safe (get-or-create + light enrichment). Follows are recorded only for your own
collection (`is_me=True`), since the `follows` table means "artists/labels I follow".
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bandcamp.parse import (
    AlbumSupporters,
    FanCollection,
    ParsedAlbum,
    ParsedBand,
    ParsedItem,
    ParsedTrackPage,
)
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
from app.enums import BandKind, ItemType, TargetType


@dataclass(slots=True)
class IngestCounts:
    fan_items: int = 0  # new ownership edges created this ingest
    wishlist_items: int = 0  # new wishlist edges created this ingest
    follows: int = 0  # new follows created this ingest (is_me only)


@dataclass(slots=True)
class AlbumIngestCounts:
    tracks: int = 0  # new tracks created this ingest
    tags: int = 0  # new album↔tag edges created this ingest


@dataclass(slots=True)
class SupporterIngestCounts:
    supporters: int = 0  # new supporter edges created this ingest
    fans: int = 0  # new fan rows created this ingest


@dataclass(slots=True)
class TrackIngestCounts:
    tags: int = 0  # new track↔tag edges created this ingest


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
                        album: Album | None = None, track: Track | None = None,
                        is_wishlist: bool = False) -> bool:
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
            is_wishlist=is_wishlist,
        )
    )
    await session.flush()
    return True


async def ingest_item(session: AsyncSession, fan: Fan, item: ParsedItem,
                      counts: IngestCounts, *, is_wishlist: bool = False) -> None:
    band = await get_or_create_band(session, item.band)
    if item.item_type == "album":
        album = await get_or_create_album(
            session, bandcamp_id=item.item_id, url=item.url, title=item.title, band=band
        )
        if await _add_fan_item(session, fan, ItemType.ALBUM, album=album,
                               is_wishlist=is_wishlist):
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
        if await _add_fan_item(session, fan, ItemType.TRACK, track=track,
                               is_wishlist=is_wishlist):
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

    # Wishlist (and follows) are only meaningful for my own account — they drive
    # curation's exclusions, and we only see them on the seed fan's own page.
    if is_me:
        wl_counts = IngestCounts()
        for item in fc.wishlist:
            await ingest_item(session, fan, item, wl_counts, is_wishlist=True)
        counts.wishlist_items = wl_counts.fan_items

        for pb in fc.follows:
            band = await get_or_create_band(session, pb)
            if band and await upsert_follow(session, band):
                counts.follows += 1

    await session.commit()
    return counts


# ── Album page ────────────────────────────────────────────────────────────────


async def get_or_create_tag(session: AsyncSession, name: str) -> Tag:
    tag = (
        await session.execute(select(Tag).where(Tag.name == name))
    ).scalar_one_or_none()
    if tag is None:
        tag = Tag(name=name)
        session.add(tag)
        await session.flush()
    return tag


async def _add_album_tag(session: AsyncSession, album: Album, tag: Tag) -> bool:
    """Link an album to a tag if not already linked. True if a new edge was created."""
    exists = (
        await session.execute(
            select(AlbumTag).where(
                AlbumTag.album_id == album.id, AlbumTag.tag_id == tag.id
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        return False
    session.add(AlbumTag(album_id=album.id, tag_id=tag.id))
    await session.flush()
    return True


async def _link_tag(session: AsyncSession, model, id_col, obj_id: int, tag_id: int) -> bool:
    """Idempotently link a band/track to a tag (composite-PK association).
    True if a new edge was created."""
    exists = (
        await session.execute(select(model).where(id_col == obj_id, model.tag_id == tag_id))
    ).scalar_one_or_none()
    if exists is not None:
        return False
    session.add(model(**{id_col.key: obj_id, "tag_id": tag_id}))
    await session.flush()
    return True


async def ingest_album(session: AsyncSession, pa: ParsedAlbum) -> AlbumIngestCounts:
    """Upsert an album, its band, tracks, and genre tags (idempotent).

    Tags parsed from the album page are linked at three levels: the album
    (`album_tags`), its band (`band_tags` — a band accumulates its releases' tags),
    and each of its tracks (`track_tags`).
    """
    counts = AlbumIngestCounts()
    band = await get_or_create_band(session, pa.band)
    album = await get_or_create_album(
        session, bandcamp_id=pa.album_id, url=pa.url, title=pa.title, band=band
    )

    tracks: list[Track] = []
    for pt in pa.tracks:
        existing = (
            await session.execute(select(Track).where(Track.bandcamp_id == pt.track_id))
        ).scalar_one_or_none()
        if existing is None:
            counts.tracks += 1
        tracks.append(
            await get_or_create_track(
                session, bandcamp_id=pt.track_id, url=pt.url, title=pt.title,
                band=band, album=album,
            )
        )

    for name in pa.tags:
        tag = await get_or_create_tag(session, name)
        if await _add_album_tag(session, album, tag):
            counts.tags += 1
        if band is not None:
            await _link_tag(session, BandTag, BandTag.band_id, band.id, tag.id)
        for track in tracks:
            await _link_tag(session, TrackTag, TrackTag.track_id, track.id, tag.id)

    await session.commit()
    return counts


async def ingest_track_page(session: AsyncSession, pt: ParsedTrackPage) -> TrackIngestCounts:
    """Upsert a standalone track (its own `/track/` page), its band, and genre tags.

    Unlike `ingest_album`, there's no `trackinfo[]` sibling list to walk — just this
    one track. If it belongs to an album we only record a stub `Album` row (id/url,
    from the track page's `current.album_id`/`album_url`) so the two can be linked
    later; that album's own page isn't crawled here, so no album_tags are written
    for it — only track_tags (and band_tags, same as `ingest_album`).
    """
    counts = TrackIngestCounts()
    band = await get_or_create_band(session, pt.band)
    album = None
    if pt.album_id is not None:
        album = await get_or_create_album(
            session, bandcamp_id=pt.album_id, url=pt.album_url, band=band
        )
    track = await get_or_create_track(
        session, bandcamp_id=pt.track_id, url=pt.url, title=pt.title, band=band, album=album
    )

    for name in pt.tags:
        tag = await get_or_create_tag(session, name)
        if await _link_tag(session, TrackTag, TrackTag.track_id, track.id, tag.id):
            counts.tags += 1
        if band is not None:
            await _link_tag(session, BandTag, BandTag.band_id, band.id, tag.id)

    await session.commit()
    return counts


# ── Album supporters ──────────────────────────────────────────────────────────


async def get_or_create_supporter_fan(
    session: AsyncSession, *, username: str, fan_id: int | None, name: str | None
) -> tuple[Fan, bool]:
    """Get-or-create a fan seen as an album supporter. Returns (fan, created).

    Keyed by bandcamp_fan_id when known, else by username (fan pages may be
    discovered by username before their fan_id is). Backfills fan_id/name.
    """
    fan: Fan | None = None
    if fan_id is not None:
        fan = (
            await session.execute(select(Fan).where(Fan.bandcamp_fan_id == fan_id))
        ).scalar_one_or_none()
    if fan is None:
        fan = (
            await session.execute(select(Fan).where(Fan.username == username))
        ).scalar_one_or_none()
    if fan is None:
        fan = Fan(
            bandcamp_fan_id=fan_id,
            username=username,
            url=f"https://bandcamp.com/{username}",
            name=name,
        )
        session.add(fan)
        await session.flush()
        return fan, True
    if fan_id is not None and fan.bandcamp_fan_id is None:
        fan.bandcamp_fan_id = fan_id
    if name and not fan.name:
        fan.name = name
    return fan, False


async def _add_album_supporter(
    session: AsyncSession, album: Album, fan: Fan
) -> bool:
    """Record a fan↔album supporter edge if absent. True if newly created."""
    exists = (
        await session.execute(
            select(AlbumSupporter).where(
                AlbumSupporter.album_id == album.id, AlbumSupporter.fan_id == fan.id
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        return False
    session.add(AlbumSupporter(album_id=album.id, fan_id=fan.id))
    await session.flush()
    return True


async def ingest_album_supporters(
    session: AsyncSession, album: Album, supporters: AlbumSupporters
) -> SupporterIngestCounts:
    """Upsert supporter fans and their support edges for a known album."""
    counts = SupporterIngestCounts()
    for ps in supporters.supporters:
        fan, created = await get_or_create_supporter_fan(
            session, username=ps.username, fan_id=ps.fan_id, name=ps.name
        )
        if created:
            counts.fans += 1
        if await _add_album_supporter(session, album, fan):
            counts.supporters += 1
    await session.commit()
    return counts


async def _add_track_supporter(session: AsyncSession, track: Track, fan: Fan) -> bool:
    """Record a fan↔track supporter edge if absent. True if newly created."""
    exists = (
        await session.execute(
            select(TrackSupporter).where(
                TrackSupporter.track_id == track.id, TrackSupporter.fan_id == fan.id
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        return False
    session.add(TrackSupporter(track_id=track.id, fan_id=fan.id))
    await session.flush()
    return True


async def ingest_track_supporters(
    session: AsyncSession, track: Track, supporters: AlbumSupporters
) -> SupporterIngestCounts:
    """Upsert supporter fans and their support edges for a known track.

    Takes the same `AlbumSupporters` shape `parse_album_supporters` returns for a
    track page (it's tralbum-generic — see its `tralbum_type` field)."""
    counts = SupporterIngestCounts()
    for ps in supporters.supporters:
        fan, created = await get_or_create_supporter_fan(
            session, username=ps.username, fan_id=ps.fan_id, name=ps.name
        )
        if created:
            counts.fans += 1
        if await _add_track_supporter(session, track, fan):
            counts.supporters += 1
    await session.commit()
    return counts
