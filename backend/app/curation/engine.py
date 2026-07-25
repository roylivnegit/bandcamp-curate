"""Score candidate music into the `recommendations` table.

Signal (POC): **co-ownership among taste-neighbours** — how many crawled fans (people
who share your collection) also own an item — plus a **tag-affinity** nudge from the
genres you already collect. Everything already in your world is excluded first:

  * owned      — your `fan_items` (is_wishlist = false)
  * wishlisted — your `fan_items` (is_wishlist = true)
  * followed   — items whose band is in `follows`
  * blacklisted — active `blacklist` rows

"You" is the `is_me` fan (set from BANDCAMP_FAN_URL at seed time) — i.e. the original
collection we started crawling from. Recommendations are recomputed wholesale
(clear + insert) so re-running is idempotent.
"""

import re
from dataclasses import dataclass, field

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

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
    Scan,
    ScanSeed,
    Tag,
    Track,
)
from app.enums import ItemType, ScanKind, ScanStatus

# Weights — co-ownership dominates; tag affinity breaks ties. Tune later
# (eventually from an active `curation_rules` row).
W_CO_OWNER = 1.0
W_TAG_AFFINITY = 0.25


@dataclass(slots=True)
class ScoredItem:
    item_type: str
    album_id: int | None
    track_id: int | None
    score: float
    band_id: int | None = None
    reasons: dict = field(default_factory=dict)


@dataclass(slots=True)
class Exclusions:
    album_ids: set[int]
    track_ids: set[int]
    band_ids: set[int]
    band_hosts: set[str]  # url hosts of followed bands (e.g. "atomesmusic.bandcamp.com")


def _url_host(url: str | None) -> str | None:
    """The host of a Bandcamp URL, e.g. https://atomesmusic.bandcamp.com/album/x → host."""
    if not url:
        return None
    m = re.match(r"https?://([^/]+)", url)
    return m.group(1).lower() if m else None


async def get_me(session: AsyncSession) -> Fan:
    me = (
        await session.execute(select(Fan).where(Fan.is_me.is_(True)))
    ).scalars().first()
    if me is None:
        raise ValueError("no is_me fan — seed and crawl your own collection first")
    return me


async def _scalar_set(session: AsyncSession, stmt) -> set[int]:
    return {r for r in (await session.execute(stmt)).scalars() if r is not None}


async def ensure_collection_scan(session: AsyncSession) -> Scan:
    """Get-or-create the "My collection" scan (kind=collection) — Scan 1, whose
    seeds are your own owned albums. A fresh DB has no scan rows (metadata builds
    only tables), so we create it lazily here on first curate."""
    scan = (
        await session.execute(
            select(Scan).where(Scan.kind == str(ScanKind.COLLECTION)).order_by(Scan.id)
        )
    ).scalars().first()
    if scan is None:
        scan = Scan(
            name="My collection",
            kind=str(ScanKind.COLLECTION),
            status=str(ScanStatus.DONE),
        )
        session.add(scan)
        await session.flush()
    return scan


async def _seed_album_ids(session: AsyncSession, scan: Scan, me: Fan) -> set[int]:
    """The album ids whose supporters form this scan's taste-neighbour set.

    collection → your owned albums; custom → the scan's resolved album seeds.
    (Track seeds resolve to track supporters — added in Stage 2.)
    """
    if scan.kind == str(ScanKind.COLLECTION):
        return await _scalar_set(
            session,
            select(FanItem.album_id).where(
                FanItem.fan_id == me.id,
                FanItem.is_wishlist.is_(False),
                FanItem.album_id.isnot(None),
            ),
        )
    return await _scalar_set(
        session,
        select(ScanSeed.resolved_album_id).where(
            ScanSeed.scan_id == scan.id, ScanSeed.resolved_album_id.isnot(None)
        ),
    )


async def build_exclusions(session: AsyncSession, me: Fan) -> Exclusions:
    """Everything already in your world — never recommend these."""
    # Owned + wishlisted (both live in your fan_items).
    my_albums = await _scalar_set(
        session, select(FanItem.album_id).where(FanItem.fan_id == me.id)
    )
    my_tracks = await _scalar_set(
        session, select(FanItem.track_id).where(FanItem.fan_id == me.id)
    )
    # Bands you follow (by id and by URL host — a followed label and an album's
    # artist can differ by band_id but share the label's subdomain).
    followed = await _scalar_set(session, select(Follow.band_id))
    followed_urls = (
        await session.execute(
            select(Band.url).select_from(Follow).join(Band, Band.id == Follow.band_id)
        )
    ).scalars()
    band_hosts = {h for h in (_url_host(u) for u in followed_urls) if h}
    # Active blacklist.
    bl_albums = await _scalar_set(
        session, select(Blacklist.album_id).where(Blacklist.active.is_(True))
    )
    bl_tracks = await _scalar_set(
        session, select(Blacklist.track_id).where(Blacklist.active.is_(True))
    )
    bl_bands = await _scalar_set(
        session, select(Blacklist.band_id).where(Blacklist.active.is_(True))
    )
    # Liked/acted-on items (positive dismissal). A like excludes the item AND its
    # band — liking one release of an artist means you've engaged with that artist,
    # so the whole band drops from the feed (else one-per-band dedup would just
    # re-surface it via another release).
    liked_albums = await _scalar_set(session, select(Like.album_id))
    liked_tracks = await _scalar_set(session, select(Like.track_id))
    liked_album_bands = await _scalar_set(
        session, select(Album.band_id).select_from(Like).join(Album, Album.id == Like.album_id)
    )
    liked_track_bands = await _scalar_set(
        session, select(Track.band_id).select_from(Like).join(Track, Track.id == Like.track_id)
    )
    return Exclusions(
        album_ids=my_albums | bl_albums | liked_albums,
        track_ids=my_tracks | bl_tracks | liked_tracks,
        band_ids=followed | bl_bands | liked_album_bands | liked_track_bands,
        band_hosts=band_hosts,
    )


async def _my_tag_profile(session: AsyncSession, me: Fan) -> dict[int, int]:
    """Tag id → how many of your owned albums carry it (your genre fingerprint)."""
    rows = (
        await session.execute(
            select(AlbumTag.tag_id, func.count())
            .select_from(FanItem)
            .join(AlbumTag, AlbumTag.album_id == FanItem.album_id)
            .where(FanItem.fan_id == me.id, FanItem.is_wishlist.is_(False))
            .group_by(AlbumTag.tag_id)
        )
    ).all()
    return {tag_id: n for tag_id, n in rows}


async def _album_tags(session: AsyncSession, album_ids: set[int]) -> dict[int, list[int]]:
    if not album_ids:
        return {}
    rows = (
        await session.execute(
            select(AlbumTag.album_id, AlbumTag.tag_id).where(
                AlbumTag.album_id.in_(album_ids)
            )
        )
    ).all()
    out: dict[int, list[int]] = {}
    for album_id, tag_id in rows:
        out.setdefault(album_id, []).append(tag_id)
    return out


async def _tag_names(session: AsyncSession, tag_ids: set[int]) -> dict[int, str]:
    if not tag_ids:
        return {}
    rows = (await session.execute(select(Tag.id, Tag.name).where(Tag.id.in_(tag_ids)))).all()
    return {tid: name for tid, name in rows}


async def _seed_tag_provenance(
    session: AsyncSession, seed_album_ids: set[int], me: Fan
) -> tuple[dict[int, set[str]], dict[int, set[str]]]:
    """Map each candidate → the genre tags of the scan's *seed* albums that generated it.

    A candidate is surfaced because a taste-neighbour owns it; that neighbour is in
    the scan because they support one of its seed albums. So the candidate's "seed
    genres" are the tags of the seed albums whose supporters own the candidate.
    Explains *why* something was recommended.
    """
    if not seed_album_ids:
        return {}, {}

    # For each seed album: its supporters, and everything those supporters own →
    # (candidate, seed tag) pairs.
    rows = (
        await session.execute(
            select(FanItem.album_id, FanItem.track_id, Tag.name)
            .select_from(AlbumSupporter)
            .join(FanItem, FanItem.fan_id == AlbumSupporter.fan_id)
            .join(AlbumTag, AlbumTag.album_id == AlbumSupporter.album_id)
            .join(Tag, Tag.id == AlbumTag.tag_id)
            .where(
                AlbumSupporter.album_id.in_(seed_album_ids),
                FanItem.fan_id != me.id,
            )
        )
    ).all()

    album_prov: dict[int, set[str]] = {}
    track_prov: dict[int, set[str]] = {}
    for album_id, track_id, tag_name in rows:
        if album_id is not None:
            album_prov.setdefault(album_id, set()).add(tag_name)
        elif track_id is not None:
            track_prov.setdefault(track_id, set()).add(tag_name)
    return album_prov, track_prov


async def compute_recommendations(
    session: AsyncSession,
    scan: Scan,
    *,
    limit: int | None = None,
    one_per_band: bool = True,
    exclude_seed_tags: set[str] | None = None,
) -> list[ScoredItem]:
    """Score unowned albums + tracks for one scan by co-ownership among its
    taste-neighbours (+ tag affinity).

    A scan's **neighbours** are the fans who support its seed albums (collection
    scan → your owned albums; custom scan → its resolved album seeds). Co-ownership
    is counted only among those neighbours, so each scan reflects *its* seeds.
    Exclusions (collection/wishlist/follows/blocked/liked) and the tag profile are
    shared/global. With `one_per_band` (default) only each band's top item is kept.
    """
    me = await get_me(session)
    seed_album_ids = await _seed_album_ids(session, scan, me)
    excl = await build_exclusions(session, me)
    tag_profile = await _my_tag_profile(session, me)
    album_prov, track_prov = await _seed_tag_provenance(session, seed_album_ids, me)
    exclude_seed_tags = exclude_seed_tags or set()

    # This scan's neighbours: fans who support any of its seed albums (not me).
    neighbours = (
        select(AlbumSupporter.fan_id)
        .where(AlbumSupporter.album_id.in_(seed_album_ids), AlbumSupporter.fan_id != me.id)
        .distinct()
    )

    scored: list[ScoredItem] = []

    def _excluded_album(aid: int, band_id: int | None, url: str | None) -> bool:
        return (
            aid in excl.album_ids
            or band_id in excl.band_ids
            or _url_host(url) in excl.band_hosts
        )

    # ── Album candidates: co-owners among this scan's neighbours ──────────────
    album_rows = (
        await session.execute(
            select(
                FanItem.album_id,
                Album.band_id,
                Album.url,
                func.count(func.distinct(FanItem.fan_id)).label("co_owners"),
            )
            .select_from(FanItem)
            .join(Album, Album.id == FanItem.album_id)
            .where(FanItem.album_id.isnot(None), FanItem.fan_id.in_(neighbours))
            .group_by(FanItem.album_id, Album.band_id, Album.url)
        )
    ).all()

    candidate_album_ids = {
        aid for aid, band_id, url, _ in album_rows if not _excluded_album(aid, band_id, url)
    }
    album_tags = await _album_tags(session, candidate_album_ids)
    all_tag_ids = {t for tags in album_tags.values() for t in tags}
    tag_names = await _tag_names(session, all_tag_ids)

    for album_id, band_id, url, co_owners in album_rows:
        if _excluded_album(album_id, band_id, url):
            continue
        seed_tags = album_prov.get(album_id, set())
        if exclude_seed_tags & seed_tags:
            continue
        tags = album_tags.get(album_id, [])
        matched = [tag_names[t] for t in tags if t in tag_profile]
        tag_affinity = sum(tag_profile.get(t, 0) for t in tags)
        score = W_CO_OWNER * co_owners + W_TAG_AFFINITY * tag_affinity
        scored.append(
            ScoredItem(
                item_type=str(ItemType.ALBUM),
                album_id=album_id,
                track_id=None,
                score=score,
                band_id=band_id,
                reasons={
                    "co_owners": co_owners,
                    "tag_affinity": tag_affinity,
                    "matched_tags": sorted(set(matched)),
                    "seed_tags": sorted(seed_tags),
                },
            )
        )

    # ── Track candidates: co-owners among this scan's neighbours ─────────────
    track_rows = (
        await session.execute(
            select(
                FanItem.track_id,
                Track.band_id,
                Track.url,
                func.count(func.distinct(FanItem.fan_id)).label("co_owners"),
            )
            .select_from(FanItem)
            .join(Track, Track.id == FanItem.track_id)
            .where(FanItem.track_id.isnot(None), FanItem.fan_id.in_(neighbours))
            .group_by(FanItem.track_id, Track.band_id, Track.url)
        )
    ).all()

    for track_id, band_id, url, co_owners in track_rows:
        if (
            track_id in excl.track_ids
            or band_id in excl.band_ids
            or _url_host(url) in excl.band_hosts
        ):
            continue
        seed_tags = track_prov.get(track_id, set())
        if exclude_seed_tags & seed_tags:
            continue
        scored.append(
            ScoredItem(
                item_type=str(ItemType.TRACK),
                album_id=None,
                track_id=track_id,
                score=W_CO_OWNER * co_owners,
                band_id=band_id,
                reasons={"co_owners": co_owners, "seed_tags": sorted(seed_tags)},
            )
        )

    scored.sort(key=lambda s: s.score, reverse=True)
    if one_per_band:
        seen_bands: set[int] = set()
        deduped: list[ScoredItem] = []
        for s in scored:
            if s.band_id is not None:
                if s.band_id in seen_bands:
                    continue
                seen_bands.add(s.band_id)
            deduped.append(s)
        scored = deduped
    return scored[:limit] if limit else scored


async def store_recommendations(
    session: AsyncSession, scored: list[ScoredItem], scan_id: int
) -> int:
    """Replace one scan's recommendations with a freshly computed set."""
    await session.execute(
        delete(Recommendation).where(Recommendation.scan_id == scan_id)
    )
    for s in scored:
        session.add(
            Recommendation(
                scan_id=scan_id,
                item_type=s.item_type,
                album_id=s.album_id,
                track_id=s.track_id,
                score=s.score,
                reasons=s.reasons,
            )
        )
    await session.commit()
    return len(scored)


async def curate(
    session: AsyncSession, *, scan_id: int | None = None, limit: int | None = None,
    exclude_seed_tags: set[str] | None = None,
) -> list[ScoredItem]:
    """Compute + persist recommendations for one scan (defaults to the collection
    scan). Returns the stored, ranked list."""
    if scan_id is None:
        scan = await ensure_collection_scan(session)
    else:
        scan = (
            await session.execute(select(Scan).where(Scan.id == scan_id))
        ).scalar_one_or_none()
        if scan is None:
            raise ValueError("scan not found")
    scored = await compute_recommendations(
        session, scan, limit=limit, exclude_seed_tags=exclude_seed_tags
    )
    await store_recommendations(session, scored, scan.id)
    return scored


async def seed_tags(session: AsyncSession) -> list[tuple[str, int]]:
    """Genres of your own crawled albums (the seeds), with how many albums carry each.

    These are the values the "exclude by seed genre" filter offers.
    """
    me = await get_me(session)
    rows = (
        await session.execute(
            select(Tag.name, func.count(func.distinct(AlbumTag.album_id)))
            .select_from(FanItem)
            .join(AlbumTag, AlbumTag.album_id == FanItem.album_id)
            .join(Tag, Tag.id == AlbumTag.tag_id)
            .where(FanItem.fan_id == me.id, FanItem.is_wishlist.is_(False))
            .group_by(Tag.name)
            .order_by(func.count(func.distinct(AlbumTag.album_id)).desc(), Tag.name)
        )
    ).all()
    return [(name, n) for name, n in rows]
