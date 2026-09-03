"""Feed API (M5): read the ranked recommendations + a stats summary, and trigger a
recompute. Read endpoints power the UI; recompute re-runs the curation engine.
"""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.auth.security import get_current_user
from app.config import Settings, get_settings
from app.crawl.runner import requests_used_by_scan
from app.curation.engine import cold_start_diagnostics, curate
from app.curation.engine import seed_tags as seed_tag_genres
from app.db.models import (
    Album,
    AlbumTag,
    Band,
    Fan,
    FanItem,
    Follow,
    Like,
    Recommendation,
    Scan,
    Tag,
    Track,
    TrackTag,
    User,
)
from app.db.session import get_session
from app.enums import ScanKind

router = APIRouter(prefix="/api", tags=["feed"])

# Per-user cooldown state for POST /recommendations/recompute (see
# Settings.recompute_cooldown_seconds). In-memory and keyed by user id: this is
# hardening against a scripted/retry-loop caller, not something that needs to
# survive a restart or be shared across API processes.
_last_recompute_at: dict[int, datetime] = {}


def _now() -> datetime:
    return datetime.now(UTC)


def _reset_recompute_cooldown_for_tests() -> None:
    """Test-only. Module-scope state outlives one test's DB/dependency-override
    teardown, so a test that enables the cooldown must clear it first —
    otherwise a leftover timestamp from an earlier test reusing the same
    (autoincrement-reset) user id would leak in."""
    _last_recompute_at.clear()


async def _resolve_scan_id(
    session: AsyncSession, user_id: int, scan_id: int | None
) -> int | None:
    """The scan to scope the feed to: the given id (must belong to `user_id` — 404s
    otherwise, never leaking another tenant's scan), else the user's own collection
    scan. Returns None only when no scan_id was given and they have no scans yet
    (→ an empty feed, not an error)."""
    if scan_id is not None:
        owner = (
            await session.execute(select(Scan.user_id).where(Scan.id == scan_id))
        ).scalars().first()
        if owner is None or owner != user_id:
            raise HTTPException(status_code=404, detail="scan not found")
        return scan_id
    return (
        await session.execute(
            select(Scan.id)
            .where(Scan.user_id == user_id, Scan.kind == str(ScanKind.COLLECTION))
            .order_by(Scan.id)
        )
    ).scalars().first()


class Reasons(BaseModel):
    co_owners: int = 0
    tag_affinity: float = 0.0
    matched_tags: list[str] = []
    seed_tags: list[str] = []  # genres of your albums that generated this rec


class RecommendationOut(BaseModel):
    rank: int
    item_type: str
    score: float
    album_id: int | None
    track_id: int | None
    title: str | None
    band_id: int | None
    band_name: str | None
    url: str | None
    reasons: Reasons
    # The scan's `recompute_generation` at fetch time — see migration 0013.
    # Every row in one response carries the same value: `store_recommendations`
    # clears + inserts inside one transaction, so a reader never sees a mix of
    # two generations. Lets the frontend tell "I'm still holding the ranking
    # this page came from" from "a recompute already replaced it".
    recompute_generation: int = 0


class Facet(BaseModel):
    value: str
    label: str
    count: int


class FacetsOut(BaseModel):
    tags: list[Facet]
    labels: list[Facet]
    seed_tags: list[Facet]  # genres of your own albums (for the seed-exclusion filter)


class ColdStartOut(BaseModel):
    """Why the feed came back thin or empty for this scan — see
    `curation.engine.cold_start_diagnostics`."""

    neighbour_count: int
    candidates: int
    excluded_owned: int
    excluded_wishlisted: int
    excluded_followed: int
    excluded_blacklisted: int


class StatsOut(BaseModel):
    recommendations: int
    fans: int
    neighbours: int
    albums: int
    tracks: int
    my_owned: int
    my_wishlist: int
    follows: int
    liked: int
    requests_used: int
    request_budget: int
    cold_start: ColdStartOut | None = None
    recompute_generation: int | None = None


async def _count(session: AsyncSession, stmt) -> int:
    return (await session.execute(stmt)).scalar_one()


async def _scan_generation(session: AsyncSession, sid: int | None) -> int:
    """`scans.recompute_generation` for `sid`, or 0 when there's no scan yet
    (a brand-new user) — mirrors the `or 0` already used when building
    `RecommendationOut` rows below."""
    if sid is None:
        return 0
    return (
        (await session.execute(select(Scan.recompute_generation).where(Scan.id == sid)))
        .scalars().first()
    ) or 0


def _generation_etag(sid: int | None, generation: int) -> str:
    """A weak identifier for "this scan's feed as of this recompute" — every
    read endpoint scoped to one scan's recommendations (recs, facets) changes
    only when `store_recommendations` bumps the generation (see migration
    0013), so it doubles as a conditional-GET cache key: unchanged generation
    ⇒ byte-identical response for the same request URL (filters and all,
    since the URL — not the ETag alone — is what a client/cache keys on)."""
    return f'"gen-{sid if sid is not None else "none"}-{generation}"'


def _has_tag(names: list[str]):
    """EXISTS: the recommendation's album OR track carries any of these genre tags."""
    album_match = exists(
        select(1)
        .select_from(AlbumTag)
        .join(Tag, Tag.id == AlbumTag.tag_id)
        .where(AlbumTag.album_id == Recommendation.album_id, Tag.name.in_(names))
    )
    track_match = exists(
        select(1)
        .select_from(TrackTag)
        .join(Tag, Tag.id == TrackTag.tag_id)
        .where(TrackTag.track_id == Recommendation.track_id, Tag.name.in_(names))
    )
    return album_match | track_match


def _ilike_escape(s: str) -> str:
    """Escape LIKE wildcards so a literal `%`/`_`/`\\` in user input stays literal."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _has_tag_like(substrings: list[str]):
    """EXISTS: the recommendation's album OR track carries a tag whose name contains
    ANY of these (case-insensitive) substrings, e.g. "psy" matches "psybient"."""
    cond = or_(*(Tag.name.ilike(f"%{_ilike_escape(s)}%", escape="\\") for s in substrings))
    album_match = exists(
        select(1)
        .select_from(AlbumTag)
        .join(Tag, Tag.id == AlbumTag.tag_id)
        .where(AlbumTag.album_id == Recommendation.album_id, cond)
    )
    track_match = exists(
        select(1)
        .select_from(TrackTag)
        .join(Tag, Tag.id == TrackTag.tag_id)
        .where(TrackTag.track_id == Recommendation.track_id, cond)
    )
    return album_match | track_match


def _rec_order(sort: str):
    """ORDER BY clause for the feed. `co_owners`/`tag_affinity` live in the
    `reasons` JSON (portable extraction via as_integer/as_float); score is a
    column. Every option breaks ties on score then id for a stable page order."""
    tie = (Recommendation.score.desc(), Recommendation.id)
    # Order on the reasons-JSON keys. Push rows MISSING the key last via an
    # `IS NULL` sort key (False<True → non-null first) rather than COALESCE-to-0,
    # which would conflate a missing key with a legitimate 0. Portable: the
    # boolean expression sorts 0/1 on both Postgres and SQLite.
    if sort == "neighbours":
        co = Recommendation.reasons["co_owners"].as_integer()
        return (co.is_(None).asc(), co.desc(), *tie)
    if sort == "affinity":
        aff = Recommendation.reasons["tag_affinity"].as_float()
        return (aff.is_(None).asc(), aff.desc(), *tie)
    return tie  # "score" (default)


def _apply_rec_filters(stmt, band_id_col, *, item_type, tag, exclude_tag,
                       tag_contains, exclude_tag_contains,
                       label_id, exclude_label_id):
    """Apply the shared feed filters (item_type / tags / labels) to a query."""
    if item_type:
        stmt = stmt.where(Recommendation.item_type == item_type)
    if label_id:
        stmt = stmt.where(band_id_col.in_(label_id))
    if exclude_label_id:
        stmt = stmt.where(band_id_col.notin_(exclude_label_id))
    # Include = AND: the item must carry EVERY selected genre (one EXISTS each).
    for t in tag:
        stmt = stmt.where(_has_tag([t]))
    # Same AND semantics for substring filters, e.g. tag_contains=psy&tag_contains=live.
    for s in tag_contains:
        stmt = stmt.where(_has_tag_like([s]))
    # Exclude = drop the item if it carries ANY excluded genre (exact or substring).
    if exclude_tag:
        stmt = stmt.where(~_has_tag(exclude_tag))
    if exclude_tag_contains:
        stmt = stmt.where(~_has_tag_like(exclude_tag_contains))
    return stmt


@router.get("/stats", response_model=StatsOut)
async def stats(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(get_current_user),
    scan_id: int | None = Query(None),
) -> StatsOut:
    sid = await _resolve_scan_id(session, current_user.id, scan_id)
    me = current_user.fan_id  # the Fan that IS this user, once their collection is crawled
    # Every crawled collector except your own account. Must NOT filter on
    # `Fan.is_me`: that flag is set on each tenant's own fan, so excluding all of
    # them would drop other users' fans from your count even though they're
    # perfectly good neighbours in your graph.
    neighbours_stmt = select(func.count()).select_from(Fan)
    if me is not None:
        neighbours_stmt = neighbours_stmt.where(Fan.id != me)
    owned = wished = follows = 0
    if me is not None:
        owned = await _count(
            session,
            select(func.count()).select_from(FanItem).where(
                FanItem.fan_id == me, FanItem.is_wishlist.is_(False)
            ),
        )
        wished = await _count(
            session,
            select(func.count()).select_from(FanItem).where(
                FanItem.fan_id == me, FanItem.is_wishlist.is_(True)
            ),
        )
        follows = await _count(
            session, select(func.count()).select_from(Follow).where(Follow.fan_id == me)
        )
    cold_start = None
    recompute_generation = None
    if sid is not None:
        scan = await session.get(Scan, sid)
        if scan is not None:
            recompute_generation = scan.recompute_generation
            if me is not None:
                diag = await cold_start_diagnostics(session, scan, current_user)
                cold_start = ColdStartOut(
                    neighbour_count=diag.neighbour_count,
                    candidates=diag.candidates,
                    excluded_owned=diag.excluded_by_reason["owned"],
                    excluded_wishlisted=diag.excluded_by_reason["wishlisted"],
                    excluded_followed=diag.excluded_by_reason["followed"],
                    excluded_blacklisted=diag.excluded_by_reason["blacklisted"],
                )
    return StatsOut(
        recommendations=await _count(
            session,
            select(func.count()).select_from(Recommendation).where(Recommendation.scan_id == sid),
        ),
        fans=await _count(session, select(func.count()).select_from(Fan)),
        neighbours=await _count(session, neighbours_stmt),
        albums=await _count(session, select(func.count()).select_from(Album)),
        tracks=await _count(session, select(func.count()).select_from(Track)),
        my_owned=owned,
        my_wishlist=wished,
        follows=follows,
        liked=await _count(
            session, select(func.count()).select_from(Like).where(Like.user_id == current_user.id)
        ),
        requests_used=await requests_used_by_scan(session, sid) if sid is not None else 0,
        request_budget=settings.crawl_max_requests_per_scan,
        cold_start=cold_start,
        recompute_generation=recompute_generation,
    )


@router.get("/recommendations", response_model=list[RecommendationOut])
async def recommendations(
    response: Response,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
    if_none_match: str | None = Header(None, alias="If-None-Match"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    item_type: str | None = Query(None, pattern="^(album|track)$"),
    tag: list[str] = Query(default=[]),           # filter by: album has ANY of these tags
    exclude_tag: list[str] = Query(default=[]),   # filter out: album has ANY of these tags
    tag_contains: list[str] = Query(default=[]),          # filter by: tag name contains this text
    exclude_tag_contains: list[str] = Query(default=[]),  # filter out: tag name contains this text
    label_id: list[int] = Query(default=[]),      # filter by: recommendation's band
    exclude_label_id: list[int] = Query(default=[]),
    sort: str = Query("score", pattern="^(score|neighbours|affinity)$"),
    scan_id: int | None = Query(None),            # which scan's feed (default: collection)
) -> list[RecommendationOut]:
    sid = await _resolve_scan_id(session, current_user.id, scan_id)
    # Cheap enough to compute before the (filtered, joined) main query: when it
    # matches what the caller already has cached, this skips that query
    # entirely rather than only skipping re-serialization.
    generation = await _scan_generation(session, sid)
    etag = _generation_etag(sid, generation)
    if if_none_match == etag:
        return Response(status_code=304, headers={"ETag": etag})
    response.headers["ETag"] = etag

    ab = aliased(Band)
    tb = aliased(Band)
    band_id_col = func.coalesce(Album.band_id, Track.band_id)
    stmt = (
        select(
            Recommendation.item_type,
            Recommendation.score,
            Recommendation.album_id,
            Recommendation.track_id,
            Recommendation.reasons,
            func.coalesce(Album.title, Track.title).label("title"),
            band_id_col.label("band_id"),
            func.coalesce(ab.name, tb.name).label("band_name"),
            func.coalesce(Album.url, Track.url).label("url"),
        )
        .select_from(Recommendation)
        .outerjoin(Album, Album.id == Recommendation.album_id)
        .outerjoin(Track, Track.id == Recommendation.track_id)
        .outerjoin(ab, ab.id == Album.band_id)
        .outerjoin(tb, tb.id == Track.band_id)
        .order_by(*_rec_order(sort))
    )
    stmt = _apply_rec_filters(
        stmt, band_id_col, item_type=item_type, tag=tag, exclude_tag=exclude_tag,
        tag_contains=tag_contains, exclude_tag_contains=exclude_tag_contains,
        label_id=label_id, exclude_label_id=exclude_label_id,
    )
    stmt = stmt.where(Recommendation.scan_id == sid).limit(limit).offset(offset)

    rows = (await session.execute(stmt)).all()
    # `generation` (and its ETag) were computed above, before this query ran —
    # all rows necessarily belong to it regardless (store_recommendations
    # clears + inserts inside one transaction), so there's nothing to re-derive
    # per row.
    return [
        RecommendationOut(
            rank=offset + i + 1,
            item_type=r.item_type,
            score=round(r.score, 2),
            album_id=r.album_id,
            track_id=r.track_id,
            title=r.title,
            band_id=r.band_id,
            band_name=r.band_name,
            url=r.url,
            reasons=Reasons(**(r.reasons or {})),
            recompute_generation=generation,
        )
        for i, r in enumerate(rows)
    ]


@router.get("/recommendations/count")
async def recommendations_count(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
    item_type: str | None = Query(None, pattern="^(album|track)$"),
    tag: list[str] = Query(default=[]),
    exclude_tag: list[str] = Query(default=[]),
    tag_contains: list[str] = Query(default=[]),
    exclude_tag_contains: list[str] = Query(default=[]),
    label_id: list[int] = Query(default=[]),
    exclude_label_id: list[int] = Query(default=[]),
    scan_id: int | None = Query(None),
) -> dict[str, int]:
    """How many recommendations match the current filters (for the feed's count header)."""
    sid = await _resolve_scan_id(session, current_user.id, scan_id)
    band_id_col = func.coalesce(Album.band_id, Track.band_id)
    stmt = (
        select(func.count())
        .select_from(Recommendation)
        .outerjoin(Album, Album.id == Recommendation.album_id)
        .outerjoin(Track, Track.id == Recommendation.track_id)
    )
    stmt = _apply_rec_filters(
        stmt, band_id_col, item_type=item_type, tag=tag, exclude_tag=exclude_tag,
        tag_contains=tag_contains, exclude_tag_contains=exclude_tag_contains,
        label_id=label_id, exclude_label_id=exclude_label_id,
    )
    stmt = stmt.where(Recommendation.scan_id == sid)
    return {"count": (await session.execute(stmt)).scalar_one()}


@router.get("/facets", response_model=FacetsOut)
async def facets(
    response: Response,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
    if_none_match: str | None = Header(None, alias="If-None-Match"),
    scan_id: int | None = Query(None),
) -> FacetsOut:
    """Tags and labels present in one scan's recommendations, with counts."""
    sid = await _resolve_scan_id(session, current_user.id, scan_id)
    # Same ETag as /recommendations: tied to the scan's recompute_generation,
    # which is what every facet here is actually joined against. The one gap —
    # `seed_tags` reflects the caller's own album tags, which could in theory
    # change without a recompute — matches this scan's other read endpoints and
    # wasn't worth a second cache key for.
    generation = await _scan_generation(session, sid)
    etag = _generation_etag(sid, generation)
    if if_none_match == etag:
        return Response(status_code=304, headers={"ETag": etag})
    response.headers["ETag"] = etag

    # Union album-tag and track-tag matches — an inner join on AlbumTag alone
    # (the old shape) never matches a track recommendation (album_id is NULL),
    # so a genre that only tracks carry silently never showed up as a facet.
    album_tag_names = (
        select(Tag.name)
        .select_from(Recommendation)
        .join(AlbumTag, AlbumTag.album_id == Recommendation.album_id)
        .join(Tag, Tag.id == AlbumTag.tag_id)
        .where(Recommendation.scan_id == sid)
    )
    track_tag_names = (
        select(Tag.name)
        .select_from(Recommendation)
        .join(TrackTag, TrackTag.track_id == Recommendation.track_id)
        .join(Tag, Tag.id == TrackTag.tag_id)
        .where(Recommendation.scan_id == sid)
    )
    tag_names = album_tag_names.union_all(track_tag_names).subquery()
    tag_rows = (
        await session.execute(
            select(tag_names.c.name, func.count().label("n"))
            .group_by(tag_names.c.name)
            .order_by(func.count().desc(), tag_names.c.name)
        )
    ).all()
    label_rows = (
        await session.execute(
            select(Band.id, Band.name, func.count().label("n"))
            .select_from(Recommendation)
            .outerjoin(Album, Album.id == Recommendation.album_id)
            .outerjoin(Track, Track.id == Recommendation.track_id)
            .join(Band, Band.id == func.coalesce(Album.band_id, Track.band_id))
            .where(Recommendation.scan_id == sid)
            .group_by(Band.id, Band.name)
            .order_by(func.count().desc(), Band.name)
            .limit(200)
        )
    ).all()
    # Seed genres come from the caller's own crawled collection. A brand-new user
    # has none yet (fan_id unset) — an empty facet list, not an error: this is the
    # first page they see after signing up.
    seed = [] if current_user.fan_id is None else await seed_tag_genres(session, current_user)
    return FacetsOut(
        tags=[Facet(value=n, label=n, count=c) for n, c in tag_rows],
        labels=[
            Facet(value=str(bid), label=name or "unknown", count=c)
            for bid, name, c in label_rows
        ],
        seed_tags=[Facet(value=n, label=n, count=c) for n, c in seed],
    )


@router.post("/recommendations/recompute")
async def recompute(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(get_current_user),
    exclude_seed_tag: list[str] = Query(default=[]),
    scan_id: int | None = Query(None),
) -> dict[str, Any]:
    """Recompute one scan's feed (defaults to the collection scan). `exclude_seed_tag`
    drops recs generated from the scan's seeds carrying those genres."""
    # Checked before the cooldown gate: an invalid scan_id is a deterministic
    # 404 that would otherwise still consume a caller's cooldown window,
    # locking a legitimate follow-up call behind a 429 it doesn't deserve.
    if scan_id is not None:
        owner = (
            await session.execute(select(Scan.user_id).where(Scan.id == scan_id))
        ).scalars().first()
        if owner is None or owner != current_user.id:
            raise HTTPException(status_code=404, detail="scan not found")

    previous_recompute_at = None
    if settings.recompute_cooldown_seconds > 0:
        now = _now()
        previous_recompute_at = _last_recompute_at.get(current_user.id)
        if previous_recompute_at is not None:
            remaining = (
                settings.recompute_cooldown_seconds
                - (now - previous_recompute_at).total_seconds()
            )
            if remaining > 0:
                raise HTTPException(
                    status_code=429,
                    detail="Recompute was called too recently — try again shortly.",
                    headers={"Retry-After": str(int(remaining) + 1)},
                )
        # Recorded before the (potentially slow) curate() call, so two rapid
        # calls can't both slip past the check while the first is still
        # running — rolled back below if curate() itself fails, so a genuine
        # error doesn't consume a caller's retry window.
        _last_recompute_at[current_user.id] = now

    try:
        scored = await curate(
            session, scan_id=scan_id, user=current_user, exclude_seed_tags=set(exclude_seed_tag)
        )
    except ValueError as e:  # e.g. collection not yet crawled → 404, not a 500
        if settings.recompute_cooldown_seconds > 0:
            if previous_recompute_at is not None:
                _last_recompute_at[current_user.id] = previous_recompute_at
            else:
                _last_recompute_at.pop(current_user.id, None)
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"computed": len(scored), "excluded_seed_tags": exclude_seed_tag}
