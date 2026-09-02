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

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bandcamp.urls import url_host
from app.config import get_settings
from app.db.models import (
    Album,
    AlbumSupporter,
    AlbumTag,
    Band,
    BandTag,
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
# Unweighted path only (weighted_co_owners=False) — the pre-ADR-0002 formula, raw
# tag_affinity. Parity tests pin this exact value; do not touch it for the weighted path.
W_TAG_AFFINITY = 0.25
# ADR-0003: weighted path only. co_owner_weight there sums `1 + log1p(overlap)` per fan,
# so a second real co-owner's minimum marginal contribution is 1.0. log1p(tag_affinity)
# tops out around 8-9 even for a genre that spans your whole ~1,700-item collection, so
# 0.1 * log1p(...) stays under 1.0 — the tag term alone can never outrank one more co-owner.
W_TAG_AFFINITY_WEIGHTED = 0.1


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
    # `expires_at` is a "not now": NULL blocks indefinitely, a past timestamp
    # stops excluding without anyone needing to unblock it by hand.
    bl_where = (
        Blacklist.user_id == user.id,
        Blacklist.active.is_(True),
        or_(Blacklist.expires_at.is_(None), Blacklist.expires_at > datetime.now(UTC)),
    )
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
    """Tag id → how many of your owned albums/tracks carry it (your genre
    fingerprint). Falls back to the band's tags where the item's own page
    hasn't been tag-crawled (see `_effective_album_tags`/`_effective_track_tags`)
    — otherwise an owned item with no page fetch yet contributes nothing to
    your fingerprint at all. Albums and tracks count the same way; owning a
    standalone track tells you just as much about your taste as owning an
    album does."""
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
    tags_by_album = await _effective_album_tags(session, album_ids)
    tags_by_track = await _effective_track_tags(session, track_ids)
    profile: dict[int, int] = {}
    for tag_ids in (*tags_by_album.values(), *tags_by_track.values()):
        for tag_id in set(tag_ids):
            profile[tag_id] = profile.get(tag_id, 0) + 1
    return profile


async def _effective_album_tags(session: AsyncSession, album_ids: set[int]) -> dict[int, list[int]]:
    """album_id → tag_ids: the album page's own tags where crawled, else the
    band's aggregated tags (`band_tags`). Tag coverage lives on album *pages*,
    which the crawl mostly doesn't fetch, so an album with zero page tags would
    otherwise never contribute to tag-affinity even though its band's genre is
    already known from other releases."""
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

    missing = album_ids - out.keys()
    if not missing:
        return out
    band_rows = (
        await session.execute(
            select(Album.id, Album.band_id).where(
                Album.id.in_(missing), Album.band_id.isnot(None)
            )
        )
    ).all()
    band_ids = {band_id for _, band_id in band_rows}
    band_tags: dict[int, list[int]] = {}
    if band_ids:
        bt_rows = (
            await session.execute(
                select(BandTag.band_id, BandTag.tag_id).where(BandTag.band_id.in_(band_ids))
            )
        ).all()
        for band_id, tag_id in bt_rows:
            band_tags.setdefault(band_id, []).append(tag_id)
    for album_id, band_id in band_rows:
        if band_id in band_tags:
            out[album_id] = band_tags[band_id]
    return out


async def _effective_track_tags(session: AsyncSession, track_ids: set[int]) -> dict[int, list[int]]:
    """track_id → tag_ids: the same idea as `_effective_album_tags`, mirrored for tracks.

    There's no technical difference between an album and a track here — both belong
    to a band and can carry page-level tags or fall back to `band_tags` — so this is
    deliberately the same logic, not a track-specific variant of it."""
    if not track_ids:
        return {}
    rows = (
        await session.execute(
            select(TrackTag.track_id, TrackTag.tag_id).where(
                TrackTag.track_id.in_(track_ids)
            )
        )
    ).all()
    out: dict[int, list[int]] = {}
    for track_id, tag_id in rows:
        out.setdefault(track_id, []).append(tag_id)

    missing = track_ids - out.keys()
    if not missing:
        return out
    band_rows = (
        await session.execute(
            select(Track.id, Track.band_id).where(
                Track.id.in_(missing), Track.band_id.isnot(None)
            )
        )
    ).all()
    band_ids = {band_id for _, band_id in band_rows}
    band_tags: dict[int, list[int]] = {}
    if band_ids:
        bt_rows = (
            await session.execute(
                select(BandTag.band_id, BandTag.tag_id).where(BandTag.band_id.in_(band_ids))
            )
        ).all()
        for band_id, tag_id in bt_rows:
            band_tags.setdefault(band_id, []).append(tag_id)
    for track_id, band_id in band_rows:
        if band_id in band_tags:
            out[track_id] = band_tags[band_id]
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

    Uses `_effective_album_tags`/`_effective_track_tags` for the *seed* item's own
    genres, same as scoring does — a seed with no page-level tags falls back to its
    band's `band_tags` instead of contributing no provenance at all. Before this,
    a seed album/track that hadn't been tag-crawled silently produced zero "via …"
    reasons for everything it surfaced, the same sparsity `_effective_album_tags`
    already fixed for scoring but this query bypassed by joining `AlbumTag`/
    `TrackTag` directly.
    """
    if not seed_album_ids and not seed_track_ids:
        return {}, {}

    seed_album_tags = await _effective_album_tags(session, seed_album_ids)
    seed_track_tags = await _effective_track_tags(session, seed_track_ids)
    tag_names = await _tag_names(
        session,
        {tid for ids in (*seed_album_tags.values(), *seed_track_tags.values()) for tid in ids},
    )
    seed_album_tag_names = {
        aid: {tag_names[tid] for tid in tids if tid in tag_names}
        for aid, tids in seed_album_tags.items()
    }
    seed_track_tag_names = {
        tid: {tag_names[gid] for gid in gids if gid in tag_names}
        for tid, gids in seed_track_tags.items()
    }

    album_prov: dict[int, set[str]] = {}
    track_prov: dict[int, set[str]] = {}

    def _collect(rows: list, seed_names: dict[int, set[str]]) -> None:
        for seed_id, cand_album_id, cand_track_id in rows:
            names = seed_names.get(seed_id)
            if not names:
                continue
            if cand_album_id is not None:
                album_prov.setdefault(cand_album_id, set()).update(names)
            elif cand_track_id is not None:
                track_prov.setdefault(cand_track_id, set()).update(names)

    # For each seed album: its supporters, and everything those supporters own →
    # (seed album, candidate) pairs, resolved to the seed's effective tags above.
    if seed_album_ids:
        _collect(
            (
                await session.execute(
                    select(AlbumSupporter.album_id, FanItem.album_id, FanItem.track_id)
                    .select_from(AlbumSupporter)
                    .join(FanItem, FanItem.fan_id == AlbumSupporter.fan_id)
                    .where(
                        AlbumSupporter.album_id.in_(seed_album_ids),
                        FanItem.fan_id != me.id,
                    )
                )
            ).all(),
            seed_album_tag_names,
        )

    # Same, for each seed track: its supporters → candidates, resolved to the
    # seed track's effective genres.
    if seed_track_ids:
        _collect(
            (
                await session.execute(
                    select(TrackSupporter.track_id, FanItem.album_id, FanItem.track_id)
                    .select_from(TrackSupporter)
                    .join(FanItem, FanItem.fan_id == TrackSupporter.fan_id)
                    .where(
                        TrackSupporter.track_id.in_(seed_track_ids),
                        FanItem.fan_id != me.id,
                    )
                )
            ).all(),
            seed_track_tag_names,
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


async def _scan_neighbours(
    session: AsyncSession, seed_album_ids: set[int], seed_track_ids: set[int], me: Fan
) -> set[int]:
    """Fans (other than you) who support any of this scan's seed albums/tracks —
    its taste-neighbours. Shared by `compute_recommendations` and
    `neighbour_size_report` so both agree on who counts as a neighbour."""
    neighbours: set[int] = set()
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
    return neighbours


async def _neighbour_overlap(
    session: AsyncSession, neighbours: set[int], my_album_ids: set[int], my_track_ids: set[int]
) -> dict[int, int]:
    """fan_id -> how many of YOUR owned items that neighbour also owns.

    A co-owner's weight is `1 + log1p(overlap(fan))` — a stranger who shares more of
    your taste counts for more than one who merely happens to own the same record.
    Deliberately a count, not a ratio: the only available denominator (a fan's own
    fan_items count) is crawl progress, not collection size — a collection visit
    is bounded and parked mid-page (crawl/service.py PAGES_PER_VISIT), so dividing
    by it would boost the fans we've crawled least, not the ones who share the
    most taste. The numerator has the same disease (a fan paged deeper has more
    measurable overlap) — `log1p` doesn't remove that bias, it bounds it: 10x the
    overlap moves a fan's own weight by roughly 1.6x, not 10x (ADR-0003).
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


def _damped_overlap_weight(overlap: int) -> float:
    """Per-fan multiplier: `1 + log1p(overlap)` — how much one co-owner's overlap
    with your own collection inflates their vote. Monotone, >= 1.0 at overlap 0,
    and sublinear so a deeply-crawled or huge-overlap neighbour can't drown out
    many tight-overlap ones (ADR-0003; see the scale-gap and sublinearity tests
    in test_curation.py)."""
    return 1.0 + math.log1p(overlap)


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
    neighbours = await _scan_neighbours(session, seed_album_ids, seed_track_ids, me)

    neighbour_overlap: dict[int, int] = {}
    if weighted_co_owners:
        my_album_ids, my_track_ids = await _my_owned_ids(session, me)
        neighbour_overlap = await _neighbour_overlap(
            session, neighbours, my_album_ids, my_track_ids
        )

    def _co_owner_weight(owners: set[int]) -> float:
        if not weighted_co_owners:
            return float(len(owners))
        # log1p, not the raw overlap count: unbounded-linear let one neighbour with
        # overlap 200 (score 201) beat fifty distinct tight co-owners at overlap 2
        # each (score 150) — the exact inversion of "many people who share my taste
        # own this" (ADR-0003). Damped: overlap 2 -> 2.10, 200 -> 6.30, 1700 -> 8.44.
        return float(sum(_damped_overlap_weight(neighbour_overlap.get(f, 0)) for f in owners))

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
    album_tags = await _effective_album_tags(session, candidate_album_ids)
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
        # reasons["tag_affinity"] below stays the raw sum regardless — only the
        # score's contribution is damped, and only on the weighted path (parity
        # with weighting off requires the untouched pre-ADR-0002 formula).
        if weighted_co_owners:
            tag_term = W_TAG_AFFINITY_WEIGHTED * math.log1p(tag_affinity)
        else:
            tag_term = W_TAG_AFFINITY * tag_affinity
        score = W_CO_OWNER * co_owner_weight + tag_term
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

    # ── Track candidates: same pair-level shape as albums, same tag treatment too —
    # there's no technical difference between an album and a track here. ──────────
    def _excluded_track(tid: int, band_id: int | None, url: str | None) -> bool:
        return (
            tid in excl.track_ids
            or band_id in excl.band_ids
            or url_host(url) in excl.band_hosts
        )

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

    candidate_track_ids = {
        tid for tid, owners in track_owners.items() if not _excluded_track(tid, *track_meta[tid])
    }
    track_tags = await _effective_track_tags(session, candidate_track_ids)
    track_tag_names = await _tag_names(
        session, {t for tags in track_tags.values() for t in tags}
    )

    for track_id, owners in track_owners.items():
        band_id, url = track_meta[track_id]
        if _excluded_track(track_id, band_id, url):
            continue
        seed_tags = track_prov.get(track_id, set())
        if exclude_seed_tags & seed_tags:
            continue
        candidates += 1
        co_owners = len(owners)
        if not _passes_floor(co_owners):
            continue
        co_owner_weight = _co_owner_weight(owners)
        tags = track_tags.get(track_id, [])
        matched = [track_tag_names[t] for t in tags if t in tag_profile]
        tag_affinity = sum(tag_profile.get(t, 0) for t in tags)
        if weighted_co_owners:
            tag_term = W_TAG_AFFINITY_WEIGHTED * math.log1p(tag_affinity)
        else:
            tag_term = W_TAG_AFFINITY * tag_affinity
        score = W_CO_OWNER * co_owner_weight + tag_term
        scored.append(
            ScoredItem(
                item_type=str(ItemType.TRACK),
                album_id=None,
                track_id=track_id,
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

    # Score alone ties constantly — most candidates are "one co-owner, no tag
    # data" (score == W_CO_OWNER, tag_term == 0), so a same-score bucket can hold
    # hundreds of items. Sorting by score alone leaves those ordered however the
    # DB happened to return the underlying rows, which Postgres does not
    # guarantee across recomputes: the same feed could silently reshuffle at the
    # exact score band Roy actually scrolls through. Break ties by the two raw
    # signals score is built from (more co-owners, then more tag affinity) so
    # equal-score items are still ranked by relevance, then fall back to a
    # stable identity key so any true remainder is deterministic run to run.
    def _tie_break_key(s: ScoredItem) -> tuple:
        co_owners = s.reasons.get("co_owners", 0)
        tag_affinity = s.reasons.get("tag_affinity", 0)
        item_type_priority = 0 if s.item_type == str(ItemType.ALBUM) else 1
        ident = s.album_id if s.album_id is not None else (s.track_id or 0)
        return (-s.score, -co_owners, -tag_affinity, item_type_priority, -ident)

    scored.sort(key=_tie_break_key)
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
    session: AsyncSession, scored: list[ScoredItem], scan: Scan
) -> int:
    """Replace one scan's recommendations with a freshly computed set.

    Bumps `scan.recompute_generation` — the tag a reader uses to tell "this
    is the same ranking I already have" from "this is a different one, even
    though the total count didn't change" (see migration `0013`). This is
    the one place every re-curate path (mid-crawl slices, finalize, the API,
    the CLI) already goes through, so it's the only place that needs to."""
    await session.execute(
        delete(Recommendation).where(Recommendation.scan_id == scan.id)
    )
    for s in scored:
        session.add(
            Recommendation(
                scan_id=scan.id,
                item_type=s.item_type,
                album_id=s.album_id,
                track_id=s.track_id,
                score=s.score,
                reasons=s.reasons,
            )
        )
    scan.recompute_generation = (scan.recompute_generation or 0) + 1
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
    await store_recommendations(session, scored, scan)
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


# Upper bounds of the recorded-collection-size buckets `neighbour_size_report` groups
# neighbours into (the last bucket is "5000+"). Backlog: "Mega-supporters flatten the
# signal" — measure the actual distribution before building anything to correct for it.
NEIGHBOUR_SIZE_BUCKETS = (50, 200, 1000, 5000)


async def _collection_sizes(session: AsyncSession, fan_ids: set[int]) -> dict[int, int]:
    """fan_id -> recorded owned-item count (albums + tracks, is_wishlist=false) — a
    proxy for how big a collector's collection is. A LOWER BOUND: a fan's collection
    visit pages a bounded slice per visit and can be parked mid-crawl (see
    `_neighbour_overlap`'s note on the same issue), so an under-crawled mega-collector
    can read smaller here than their true collection."""
    if not fan_ids:
        return {}
    rows = (
        await session.execute(
            select(FanItem.fan_id, func.count())
            .where(FanItem.fan_id.in_(fan_ids), FanItem.is_wishlist.is_(False))
            .group_by(FanItem.fan_id)
        )
    ).all()
    return {fan_id: n for fan_id, n in rows}


async def _candidate_vote_counts(
    session: AsyncSession, neighbours: set[int], excl: Exclusions
) -> dict[int, int]:
    """fan_id -> how many non-excluded candidate albums/tracks they own — the raw,
    unweighted "votes" that back each item's `co_owners` count and the `min_co_owners`
    floor. Mirrors the same exclusion checks `compute_recommendations` applies to
    candidates, so this counts only votes that actually reach the feed."""
    counts: dict[int, int] = {}
    if not neighbours:
        return counts

    def _tally(rows: list, excluded_ids: set[int]) -> None:
        for fan_id, item_id, band_id, url in rows:
            excluded = (
                item_id in excluded_ids
                or band_id in excl.band_ids
                or url_host(url) in excl.band_hosts
            )
            if excluded:
                continue
            counts[fan_id] = counts.get(fan_id, 0) + 1

    album_rows = (
        await session.execute(
            select(FanItem.fan_id, FanItem.album_id, Album.band_id, Album.url)
            .select_from(FanItem)
            .join(Album, Album.id == FanItem.album_id)
            .where(FanItem.album_id.isnot(None), FanItem.fan_id.in_(neighbours))
        )
    ).all()
    _tally(album_rows, excl.album_ids)

    track_rows = (
        await session.execute(
            select(FanItem.fan_id, FanItem.track_id, Track.band_id, Track.url)
            .select_from(FanItem)
            .join(Track, Track.id == FanItem.track_id)
            .where(FanItem.track_id.isnot(None), FanItem.fan_id.in_(neighbours))
        )
    ).all()
    _tally(track_rows, excl.track_ids)
    return counts


def _size_bucket_label(size: int, bounds: tuple[int, ...]) -> str:
    lo = 0
    for b in bounds:
        if size < b:
            return f"{lo}-{b}"
        lo = b
    return f"{bounds[-1]}+"


def _size_bucket_order(bounds: tuple[int, ...]) -> list[str]:
    labels = []
    lo = 0
    for b in bounds:
        labels.append(f"{lo}-{b}")
        lo = b
    labels.append(f"{bounds[-1]}+")
    return labels


@dataclass(slots=True)
class ColdStartDiagnostics:
    """Why a scan's feed came back thin or empty: how many taste-neighbours it
    found, how many distinct items they collectively own before any exclusion
    is applied, and how many of those get excluded for each reason. A reason
    count can exceed `candidates` in total since one item can be excluded for
    more than one reason at once (e.g. wishlisted AND from a followed band)."""

    neighbour_count: int
    candidates: int
    excluded_by_reason: dict[str, int]


async def cold_start_diagnostics(
    session: AsyncSession, scan: Scan, user: User
) -> ColdStartDiagnostics:
    """Read-only diagnostic, computed separately from `compute_recommendations`'s
    own `candidates`/`filtered_by_floor` stats (which are already post-exclusion,
    since today's candidate-selection query applies exclusions in the same step
    it selects candidates) — this recomputes the pre-exclusion candidate set from
    scratch so a genuinely empty feed can be told apart from "no neighbours found"
    vs. "neighbours found but everything they own is already in your world"."""
    me = await get_me(session, user)
    seed_album_ids, seed_track_ids = await _seed_ids(session, scan, me)
    neighbours = await _scan_neighbours(session, seed_album_ids, seed_track_ids, me)

    reasons = {"owned": 0, "wishlisted": 0, "followed": 0, "blacklisted": 0}
    if not neighbours:
        return ColdStartDiagnostics(neighbour_count=0, candidates=0, excluded_by_reason=reasons)

    album_rows = (
        await session.execute(
            select(FanItem.album_id, Album.band_id, Album.url)
            .select_from(FanItem)
            .join(Album, Album.id == FanItem.album_id)
            .where(FanItem.album_id.isnot(None), FanItem.fan_id.in_(neighbours))
            .distinct()
        )
    ).all()
    track_rows = (
        await session.execute(
            select(FanItem.track_id, Track.band_id, Track.url)
            .select_from(FanItem)
            .join(Track, Track.id == FanItem.track_id)
            .where(FanItem.track_id.isnot(None), FanItem.fan_id.in_(neighbours))
            .distinct()
        )
    ).all()
    candidates = len(album_rows) + len(track_rows)

    my_owned_albums = await _scalar_set(
        session,
        select(FanItem.album_id).where(
            FanItem.fan_id == me.id, FanItem.is_wishlist.is_(False), FanItem.album_id.isnot(None)
        ),
    )
    my_wishlist_albums = await _scalar_set(
        session,
        select(FanItem.album_id).where(
            FanItem.fan_id == me.id, FanItem.is_wishlist.is_(True), FanItem.album_id.isnot(None)
        ),
    )
    my_owned_tracks = await _scalar_set(
        session,
        select(FanItem.track_id).where(
            FanItem.fan_id == me.id, FanItem.is_wishlist.is_(False), FanItem.track_id.isnot(None)
        ),
    )
    my_wishlist_tracks = await _scalar_set(
        session,
        select(FanItem.track_id).where(
            FanItem.fan_id == me.id, FanItem.is_wishlist.is_(True), FanItem.track_id.isnot(None)
        ),
    )
    followed_band_ids = await _scalar_set(
        session, select(Follow.band_id).where(Follow.fan_id == me.id)
    )
    followed_urls = (
        await session.execute(
            select(Band.url).select_from(Follow)
            .join(Band, Band.id == Follow.band_id)
            .where(Follow.fan_id == me.id)
        )
    ).scalars()
    followed_hosts = {h for h in (url_host(u) for u in followed_urls) if h}
    bl_where = (
        Blacklist.user_id == user.id,
        Blacklist.active.is_(True),
        or_(Blacklist.expires_at.is_(None), Blacklist.expires_at > datetime.now(UTC)),
    )
    bl_album_ids = await _scalar_set(session, select(Blacklist.album_id).where(*bl_where))
    bl_track_ids = await _scalar_set(session, select(Blacklist.track_id).where(*bl_where))
    bl_band_ids = await _scalar_set(session, select(Blacklist.band_id).where(*bl_where))

    def _is_followed(band_id: int | None, url: str | None) -> bool:
        return band_id in followed_band_ids or url_host(url) in followed_hosts

    for album_id, band_id, url in album_rows:
        if album_id in my_owned_albums:
            reasons["owned"] += 1
        if album_id in my_wishlist_albums:
            reasons["wishlisted"] += 1
        if _is_followed(band_id, url):
            reasons["followed"] += 1
        if album_id in bl_album_ids or band_id in bl_band_ids:
            reasons["blacklisted"] += 1

    for track_id, band_id, url in track_rows:
        if track_id in my_owned_tracks:
            reasons["owned"] += 1
        if track_id in my_wishlist_tracks:
            reasons["wishlisted"] += 1
        if _is_followed(band_id, url):
            reasons["followed"] += 1
        if track_id in bl_track_ids or band_id in bl_band_ids:
            reasons["blacklisted"] += 1

    return ColdStartDiagnostics(
        neighbour_count=len(neighbours), candidates=candidates, excluded_by_reason=reasons
    )


async def neighbour_size_report(
    session: AsyncSession,
    scan: Scan,
    user: User,
    *,
    buckets: tuple[int, ...] = NEIGHBOUR_SIZE_BUCKETS,
) -> list[dict]:
    """Bucket a scan's taste-neighbours by recorded collection size and show how much
    of the co-ownership signal each bucket contributes: their share of neighbours,
    their share of raw (unweighted) candidate votes, and their share of the
    ADR-0003-weighted score. Read-only — computes nothing that gets stored.

    Answers the backlog question ("mega-supporters flatten the signal") with data: a
    bucket whose `vote_share` badly outruns its `neighbour_share` is dominating the
    unweighted `co_owners`/`min_co_owners` floor; if its `weighted_share` stays close
    to `neighbour_share` instead, the existing overlap-with-me weighting (ADR-0003) is
    already correcting for it and the raw floor is the only piece left exposed.
    """
    me = await get_me(session, user)
    seed_album_ids, seed_track_ids = await _seed_ids(session, scan, me)
    neighbours = await _scan_neighbours(session, seed_album_ids, seed_track_ids, me)
    if not neighbours:
        return []

    my_album_ids, my_track_ids = await _my_owned_ids(session, me)
    overlap = await _neighbour_overlap(session, neighbours, my_album_ids, my_track_ids)
    sizes = await _collection_sizes(session, neighbours)
    excl = await build_exclusions(session, me, user)
    votes = await _candidate_vote_counts(session, neighbours, excl)

    bounds = tuple(sorted(buckets))
    agg: dict[str, dict] = {}
    for fan_id in neighbours:
        label = _size_bucket_label(sizes.get(fan_id, 0), bounds)
        row = agg.setdefault(
            label, {"neighbours": 0, "votes": 0, "raw_overlap": 0, "weighted": 0.0}
        )
        row["neighbours"] += 1
        row["votes"] += votes.get(fan_id, 0)
        row["raw_overlap"] += overlap.get(fan_id, 0)
        row["weighted"] += _damped_overlap_weight(overlap.get(fan_id, 0))

    total_neighbours = len(neighbours)
    total_votes = sum(r["votes"] for r in agg.values()) or 1
    total_weighted = sum(r["weighted"] for r in agg.values()) or 1.0

    out = []
    for label in _size_bucket_order(bounds):
        row = agg.get(label)
        if row is None:
            continue
        out.append(
            {
                "bucket": label,
                "neighbours": row["neighbours"],
                "neighbour_share": row["neighbours"] / total_neighbours,
                "votes": row["votes"],
                "vote_share": row["votes"] / total_votes,
                "raw_overlap": row["raw_overlap"],
                "weighted_share": row["weighted"] / total_weighted,
            }
        )
    return out
