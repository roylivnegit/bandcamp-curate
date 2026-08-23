"""Score candidate music into the `recommendations` table.

Signal (POC): **co-ownership among taste-neighbours** — how many crawled fans (people
who share your collection) also own an item — plus a **tag-affinity** nudge from the
genres you already collect. Everything already in your world is excluded first:

  * owned      — your `fan_items` (is_wishlist = false)
  * wishlisted — your `fan_items` (is_wishlist = true)
  * followed   — items whose band is in `follows`
  * blacklisted — active `blacklist` rows

"You" is `user.fan_id`'s Fan — the account whose collection scan seeded the crawl.
Recommendations are recomputed wholesale (clear + insert) so re-running is idempotent.
"""

from dataclasses import dataclass, field

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bandcamp.urls import url_host
from app.config import get_settings
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
    TrackSupporter,
    TrackTag,
    User,
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


async def get_me(session: AsyncSession, user: User) -> Fan:
    """The Fan row that IS `user` — set once their collection scan has crawled
    their own fan page (see `scan_service.run_scan`'s collection-kind branch)."""
    if user.fan_id is None:
        raise ValueError("collection not yet crawled — no fan_id set for this user")
    me = await session.get(Fan, user.fan_id)
    if me is None:
        raise ValueError("user.fan_id points at a Fan row that no longer exists")
    return me


async def _scalar_set(session: AsyncSession, stmt) -> set[int]:
    return {r for r in (await session.execute(stmt)).scalars() if r is not None}


async def ensure_collection_scan(session: AsyncSession, user: User) -> Scan:
    """Get-or-create `user`'s "My collection" scan (kind=collection). Signup now
    creates this eagerly (`scan_service.create_collection_scan`) — this is a
    defensive fallback for anywhere that still calls `curate()` without a scan_id."""
    scan = (
        await session.execute(
            select(Scan).where(Scan.user_id == user.id, Scan.kind == str(ScanKind.COLLECTION))
            .order_by(Scan.id)
        )
    ).scalars().first()
    if scan is None:
        scan = Scan(
            user_id=user.id,
            name="My collection",
            kind=str(ScanKind.COLLECTION),
            status=str(ScanStatus.DONE),
        )
        session.add(scan)
        await session.flush()
    return scan


async def _seed_ids(session: AsyncSession, scan: Scan, me: Fan) -> tuple[set[int], set[int]]:
    """(seed_album_ids, seed_track_ids) — the ids whose supporters form this
    scan's taste-neighbour set.

    collection → your owned albums (album-level only — owned standalone tracks
    don't yet feed neighbours here); custom → the scan's resolved album AND
    track seeds, any mix.
    """
    if scan.kind == str(ScanKind.COLLECTION):
        album_ids = await _scalar_set(
            session,
            select(FanItem.album_id).where(
                FanItem.fan_id == me.id,
                FanItem.is_wishlist.is_(False),
                FanItem.album_id.isnot(None),
            ),
        )
        return album_ids, set()
    album_ids = await _scalar_set(
        session,
        select(ScanSeed.resolved_album_id).where(
            ScanSeed.scan_id == scan.id, ScanSeed.resolved_album_id.isnot(None)
        ),
    )
    track_ids = await _scalar_set(
        session,
        select(ScanSeed.resolved_track_id).where(
            ScanSeed.scan_id == scan.id, ScanSeed.resolved_track_id.isnot(None)
        ),
    )
    return album_ids, track_ids


async def build_exclusions(session: AsyncSession, me: Fan, user: User) -> Exclusions:
    """Everything already in your world — never recommend these. `blacklist`
    and `likes` are scoped by `user` (per-tenant); `fan_items`/`follows` by `me`
    (per-Bandcamp-fan) — mixing them up would leak one tenant's preferences
    into another's feed."""
    # Owned + wishlisted (both live in your fan_items).
    my_albums = await _scalar_set(
        session, select(FanItem.album_id).where(FanItem.fan_id == me.id)
    )
    my_tracks = await _scalar_set(
        session, select(FanItem.track_id).where(FanItem.fan_id == me.id)
    )
    # Bands you follow (by id and by URL host — a followed label and an album's
    # artist can differ by band_id but share the label's subdomain). Scoped to
    # `me` — Follow rows are per-fan, not global (a leak here would cross tenants).
    followed = await _scalar_set(
        session, select(Follow.band_id).where(Follow.fan_id == me.id)
    )
    followed_urls = (
        await session.execute(
            select(Band.url).select_from(Follow)
            .join(Band, Band.id == Follow.band_id)
            .where(Follow.fan_id == me.id)
        )
    ).scalars()
    band_hosts = {h for h in (url_host(u) for u in followed_urls) if h}
    # Active blacklist — per-user (blocking a band is a per-tenant preference).
    bl_where = (Blacklist.user_id == user.id, Blacklist.active.is_(True))
    bl_albums = await _scalar_set(session, select(Blacklist.album_id).where(*bl_where))
    bl_tracks = await _scalar_set(session, select(Blacklist.track_id).where(*bl_where))
    bl_bands = await _scalar_set(session, select(Blacklist.band_id).where(*bl_where))
    # Liked/acted-on items (positive dismissal, per-user). A like excludes the item
    # AND its band — liking one release of an artist means you've engaged with that
    # artist, so the whole band drops from the feed (else one-per-band dedup would
    # just re-surface it via another release).
    liked_albums = await _scalar_set(
        session, select(Like.album_id).where(Like.user_id == user.id)
    )
    liked_tracks = await _scalar_set(
        session, select(Like.track_id).where(Like.user_id == user.id)
    )
    liked_album_bands = await _scalar_set(
        session,
        select(Album.band_id).select_from(Like)
        .join(Album, Album.id == Like.album_id)
        .where(Like.user_id == user.id),
    )
    liked_track_bands = await _scalar_set(
        session,
        select(Track.band_id).select_from(Like)
        .join(Track, Track.id == Like.track_id)
        .where(Like.user_id == user.id),
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
    session: AsyncSession, seed_album_ids: set[int], seed_track_ids: set[int], me: Fan
) -> tuple[dict[int, set[str]], dict[int, set[str]]]:
    """Map each candidate → the genre tags of the scan's *seed* albums/tracks that
    generated it.

    A candidate is surfaced because a taste-neighbour owns it; that neighbour is in
    the scan because they support one of its seed albums or tracks. So the
    candidate's "seed genres" are the tags of the seed item (the album's own tags,
    or a seed track's own tags) whose supporters own the candidate. Explains *why*
    something was recommended.
    """
    if not seed_album_ids and not seed_track_ids:
        return {}, {}

    album_prov: dict[int, set[str]] = {}
    track_prov: dict[int, set[str]] = {}

    def _collect(rows: list) -> None:
        for album_id, track_id, tag_name in rows:
            if album_id is not None:
                album_prov.setdefault(album_id, set()).add(tag_name)
            elif track_id is not None:
                track_prov.setdefault(track_id, set()).add(tag_name)

    # For each seed album: its supporters, and everything those supporters own →
    # (candidate, seed tag) pairs.
    if seed_album_ids:
        _collect(
            (
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
        )

    # Same, for each seed track: its supporters, tagged with the seed track's own genres.
    if seed_track_ids:
        _collect(
            (
                await session.execute(
                    select(FanItem.album_id, FanItem.track_id, Tag.name)
                    .select_from(TrackSupporter)
                    .join(FanItem, FanItem.fan_id == TrackSupporter.fan_id)
                    .join(TrackTag, TrackTag.track_id == TrackSupporter.track_id)
                    .join(Tag, Tag.id == TrackTag.tag_id)
                    .where(
                        TrackSupporter.track_id.in_(seed_track_ids),
                        FanItem.fan_id != me.id,
                    )
                )
            ).all()
        )

    return album_prov, track_prov


async def _my_owned_ids(session: AsyncSession, me: Fan) -> tuple[set[int], set[int]]:
    """(album_ids, track_ids) you actually OWN (is_wishlist=false) — the basis for
    weighting a neighbour by how much of your taste they actually share."""
    album_ids = await _scalar_set(
        session,
        select(FanItem.album_id).where(
            FanItem.fan_id == me.id, FanItem.is_wishlist.is_(False), FanItem.album_id.isnot(None)
        ),
    )
    track_ids = await _scalar_set(
        session,
        select(FanItem.track_id).where(
            FanItem.fan_id == me.id, FanItem.is_wishlist.is_(False), FanItem.track_id.isnot(None)
        ),
    )
    return album_ids, track_ids


async def _neighbour_overlap(
    session: AsyncSession, neighbours: set[int], my_album_ids: set[int], my_track_ids: set[int]
) -> dict[int, int]:
    """fan_id -> how many of YOUR owned items that neighbour also owns.

    A co-owner's weight is `1 + overlap(fan)` — a stranger who shares more of your
    taste counts for more than one who merely happens to own the same record.
    Deliberately a count, not a ratio: the only available denominator (a fan's own
    fan_items count) is crawl progress, not collection size — a collection visit
    is bounded and parked mid-page (crawl/service.py PAGES_PER_VISIT), so dividing
    by it would boost the fans we've crawled least, not the ones who share the
    most taste.
    """
    if not neighbours:
        return {}
    overlap: dict[int, int] = {}
    if my_album_ids:
        rows = (
            await session.execute(
                select(FanItem.fan_id, func.count())
                .where(FanItem.fan_id.in_(neighbours), FanItem.album_id.in_(my_album_ids))
                .group_by(FanItem.fan_id)
            )
        ).all()
        for fan_id, n in rows:
            overlap[fan_id] = overlap.get(fan_id, 0) + n
    if my_track_ids:
        rows = (
            await session.execute(
                select(FanItem.fan_id, func.count())
                .where(FanItem.fan_id.in_(neighbours), FanItem.track_id.in_(my_track_ids))
                .group_by(FanItem.fan_id)
            )
        ).all()
        for fan_id, n in rows:
            overlap[fan_id] = overlap.get(fan_id, 0) + n
    return overlap


async def compute_recommendations(
    session: AsyncSession,
    scan: Scan,
    user: User,
    *,
    limit: int | None = None,
    one_per_band: bool = True,
    exclude_seed_tags: set[str] | None = None,
    min_co_owners: int | None = None,
    weighted_co_owners: bool | None = None,
    stats_out: dict | None = None,
) -> list[ScoredItem]:
    """Score unowned albums + tracks for one scan by co-ownership among its
    taste-neighbours (+ tag affinity).

    A scan's **neighbours** are the fans who support its seed albums and/or seed
    tracks (collection scan → your owned albums; custom scan → its resolved
    album/track seeds, any mix). Co-ownership is counted only among those
    neighbours, so each scan reflects *its* seeds. Exclusions (collection/
    wishlist/follows/blocked/liked) and the tag profile are per-`user` (via their
    own `me` Fan). With `one_per_band` (default) only each band's top item is kept.

    `min_co_owners` and `weighted_co_owners` default to `Settings.curation_*` —
    every caller (the mid-crawl re-curate, finalize, the API, the CLI) sees the
    same values with no argument passed, so the running feed and the finished
    feed never rank the same data differently. The kwargs exist only so tests can
    override without monkeypatching settings. If `stats_out` is given, it is
    filled with `min_co_owners`, `weighted`, `candidates` (items considered post-
    exclusion) and `filtered_by_floor` (of those, how many the floor cut) —
    otherwise a misconfigured floor silently shrinks the feed with nothing to
    show for it.
    """
    settings = get_settings()
    if min_co_owners is None:
        min_co_owners = settings.curation_min_co_owners
    if weighted_co_owners is None:
        weighted_co_owners = settings.curation_weighted_co_owners

    me = await get_me(session, user)
    seed_album_ids, seed_track_ids = await _seed_ids(session, scan, me)
    excl = await build_exclusions(session, me, user)
    tag_profile = await _my_tag_profile(session, me)
    album_prov, track_prov = await _seed_tag_provenance(
        session, seed_album_ids, seed_track_ids, me
    )
    exclude_seed_tags = exclude_seed_tags or set()

    # This scan's neighbours: fans who support any of its seed albums or tracks (not me).
    neighbours = set()
    if seed_album_ids:
        neighbours |= await _scalar_set(
            session,
            select(AlbumSupporter.fan_id).where(
                AlbumSupporter.album_id.in_(seed_album_ids), AlbumSupporter.fan_id != me.id
            ),
        )
    if seed_track_ids:
        neighbours |= await _scalar_set(
            session,
            select(TrackSupporter.fan_id).where(
                TrackSupporter.track_id.in_(seed_track_ids), TrackSupporter.fan_id != me.id
            ),
        )

    neighbour_overlap: dict[int, int] = {}
    if weighted_co_owners:
        my_album_ids, my_track_ids = await _my_owned_ids(session, me)
        neighbour_overlap = await _neighbour_overlap(
            session, neighbours, my_album_ids, my_track_ids
        )

    def _co_owner_weight(owners: set[int]) -> float:
        if not weighted_co_owners:
            return float(len(owners))
        return float(sum(1 + neighbour_overlap.get(f, 0) for f in owners))

    scored: list[ScoredItem] = []
    candidates = 0
    filtered_by_floor = 0

    def _passes_floor(co_owners: int) -> bool:
        nonlocal filtered_by_floor
        if co_owners < min_co_owners:
            filtered_by_floor += 1
            return False
        return True

    def _excluded_album(aid: int, band_id: int | None, url: str | None) -> bool:
        return (
            aid in excl.album_ids
            or band_id in excl.band_ids
            or url_host(url) in excl.band_hosts
        )

    # ── Album candidates: pair-level rows, so the raw distinct-owner count (the
    # floor) and the per-owner weight (the score) can both be derived from the
    # same set of owning fans. ─────────────────────────────────────────────────
    album_pairs = (
        await session.execute(
            select(FanItem.album_id, Album.band_id, Album.url, FanItem.fan_id)
            .select_from(FanItem)
            .join(Album, Album.id == FanItem.album_id)
            .where(FanItem.album_id.isnot(None), FanItem.fan_id.in_(neighbours))
        )
    ).all()
    album_owners: dict[int, set[int]] = {}
    album_meta: dict[int, tuple[int | None, str | None]] = {}
    for album_id, band_id, url, fan_id in album_pairs:
        album_owners.setdefault(album_id, set()).add(fan_id)
        album_meta[album_id] = (band_id, url)

    candidate_album_ids = {
        aid for aid, owners in album_owners.items() if not _excluded_album(aid, *album_meta[aid])
    }
    album_tags = await _album_tags(session, candidate_album_ids)
    all_tag_ids = {t for tags in album_tags.values() for t in tags}
    tag_names = await _tag_names(session, all_tag_ids)

    for album_id, owners in album_owners.items():
        band_id, url = album_meta[album_id]
        if _excluded_album(album_id, band_id, url):
            continue
        seed_tags = album_prov.get(album_id, set())
        if exclude_seed_tags & seed_tags:
            continue
        candidates += 1
        co_owners = len(owners)
        if not _passes_floor(co_owners):
            continue
        co_owner_weight = _co_owner_weight(owners)
        tags = album_tags.get(album_id, [])
        matched = [tag_names[t] for t in tags if t in tag_profile]
        tag_affinity = sum(tag_profile.get(t, 0) for t in tags)
        score = W_CO_OWNER * co_owner_weight + W_TAG_AFFINITY * tag_affinity
        scored.append(
            ScoredItem(
                item_type=str(ItemType.ALBUM),
                album_id=album_id,
                track_id=None,
                score=score,
                band_id=band_id,
                reasons={
                    "co_owners": co_owners,
                    "co_owner_weight": co_owner_weight,
                    "tag_affinity": tag_affinity,
                    "matched_tags": sorted(set(matched)),
                    "seed_tags": sorted(seed_tags),
                },
            )
        )

    # ── Track candidates: same pair-level shape as albums ─────────────────────
    track_pairs = (
        await session.execute(
            select(FanItem.track_id, Track.band_id, Track.url, FanItem.fan_id)
            .select_from(FanItem)
            .join(Track, Track.id == FanItem.track_id)
            .where(FanItem.track_id.isnot(None), FanItem.fan_id.in_(neighbours))
        )
    ).all()
    track_owners: dict[int, set[int]] = {}
    track_meta: dict[int, tuple[int | None, str | None]] = {}
    for track_id, band_id, url, fan_id in track_pairs:
        track_owners.setdefault(track_id, set()).add(fan_id)
        track_meta[track_id] = (band_id, url)

    for track_id, owners in track_owners.items():
        band_id, url = track_meta[track_id]
        if (
            track_id in excl.track_ids
            or band_id in excl.band_ids
            or url_host(url) in excl.band_hosts
        ):
            continue
        seed_tags = track_prov.get(track_id, set())
        if exclude_seed_tags & seed_tags:
            continue
        candidates += 1
        co_owners = len(owners)
        if not _passes_floor(co_owners):
            continue
        co_owner_weight = _co_owner_weight(owners)
        scored.append(
            ScoredItem(
                item_type=str(ItemType.TRACK),
                album_id=None,
                track_id=track_id,
                score=W_CO_OWNER * co_owner_weight,
                band_id=band_id,
                reasons={
                    "co_owners": co_owners,
                    "co_owner_weight": co_owner_weight,
                    "seed_tags": sorted(seed_tags),
                },
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

    if stats_out is not None:
        stats_out["min_co_owners"] = min_co_owners
        stats_out["weighted"] = weighted_co_owners
        stats_out["candidates"] = candidates
        stats_out["filtered_by_floor"] = filtered_by_floor

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
    session: AsyncSession, *, scan_id: int | None = None, user: User | None = None,
    limit: int | None = None, exclude_seed_tags: set[str] | None = None,
    min_co_owners: int | None = None, weighted_co_owners: bool | None = None,
    stats_out: dict | None = None,
) -> list[ScoredItem]:
    """Compute + persist recommendations for one scan. Given `scan_id`, the owning
    user is resolved from the scan itself (so this stays self-sufficient from just
    an id); with `scan_id` omitted, `user` is required and their collection scan
    is used (get-or-created). Returns the stored, ranked list.

    `min_co_owners`/`weighted_co_owners` are test overrides only — see
    `compute_recommendations`. Real callers leave them unset so every call site
    reads the same `Settings.curation_*` values."""
    if scan_id is None:
        if user is None:
            raise ValueError("user is required when scan_id is not given")
        scan = await ensure_collection_scan(session, user)
    else:
        scan = (
            await session.execute(select(Scan).where(Scan.id == scan_id))
        ).scalar_one_or_none()
        if scan is None:
            raise ValueError("scan not found")
        user = await session.get(User, scan.user_id)
        if user is None:
            raise ValueError("scan's owning user not found")
    scored = await compute_recommendations(
        session, scan, user, limit=limit, exclude_seed_tags=exclude_seed_tags,
        min_co_owners=min_co_owners, weighted_co_owners=weighted_co_owners,
        stats_out=stats_out,
    )
    await store_recommendations(session, scored, scan.id)
    return scored


async def seed_tags(session: AsyncSession, user: User) -> list[tuple[str, int]]:
    """Genres of your own crawled albums (the seeds), with how many albums carry each.

    These are the values the "exclude by seed genre" filter offers.
    """
    me = await get_me(session, user)
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
