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
    AlbumTag,
    Band,
    Blacklist,
    Fan,
    FanItem,
    Follow,
    Recommendation,
    Tag,
    Track,
)
from app.enums import ItemType

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
    return Exclusions(
        album_ids=my_albums | bl_albums,
        track_ids=my_tracks | bl_tracks,
        band_ids=followed | bl_bands,
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


async def compute_recommendations(
    session: AsyncSession, *, limit: int | None = None
) -> list[ScoredItem]:
    """Score unowned albums + tracks by neighbour co-ownership (+ tag affinity)."""
    me = await get_me(session)
    excl = await build_exclusions(session, me)
    tag_profile = await _my_tag_profile(session, me)

    scored: list[ScoredItem] = []

    def _excluded_album(aid: int, band_id: int | None, url: str | None) -> bool:
        return (
            aid in excl.album_ids
            or band_id in excl.band_ids
            or _url_host(url) in excl.band_hosts
        )

    # ── Album candidates: co-owners among non-me fans ────────────────────────
    album_rows = (
        await session.execute(
            select(
                FanItem.album_id,
                Album.band_id,
                Album.url,
                func.count(func.distinct(FanItem.fan_id)).label("co_owners"),
            )
            .select_from(FanItem)
            .join(Fan, (Fan.id == FanItem.fan_id) & Fan.is_me.is_(False))
            .join(Album, Album.id == FanItem.album_id)
            .where(FanItem.album_id.isnot(None))
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
                reasons={
                    "co_owners": co_owners,
                    "tag_affinity": tag_affinity,
                    "matched_tags": sorted(set(matched)),
                },
            )
        )

    # ── Track candidates: co-owners only (tags live on albums) ───────────────
    track_rows = (
        await session.execute(
            select(
                FanItem.track_id,
                Track.band_id,
                Track.url,
                func.count(func.distinct(FanItem.fan_id)).label("co_owners"),
            )
            .select_from(FanItem)
            .join(Fan, (Fan.id == FanItem.fan_id) & Fan.is_me.is_(False))
            .join(Track, Track.id == FanItem.track_id)
            .where(FanItem.track_id.isnot(None))
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
        scored.append(
            ScoredItem(
                item_type=str(ItemType.TRACK),
                album_id=None,
                track_id=track_id,
                score=W_CO_OWNER * co_owners,
                reasons={"co_owners": co_owners},
            )
        )

    scored.sort(key=lambda s: s.score, reverse=True)
    return scored[:limit] if limit else scored


async def store_recommendations(
    session: AsyncSession, scored: list[ScoredItem]
) -> int:
    """Replace the recommendations table with a freshly computed set."""
    await session.execute(delete(Recommendation))
    for s in scored:
        session.add(
            Recommendation(
                item_type=s.item_type,
                album_id=s.album_id,
                track_id=s.track_id,
                score=s.score,
                reasons=s.reasons,
            )
        )
    await session.commit()
    return len(scored)


async def curate(session: AsyncSession, *, limit: int | None = None) -> list[ScoredItem]:
    """Compute + persist recommendations. Returns the stored, ranked list."""
    scored = await compute_recommendations(session, limit=limit)
    await store_recommendations(session, scored)
    return scored
