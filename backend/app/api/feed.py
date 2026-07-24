"""Feed API (M5): read the ranked recommendations + a stats summary, and trigger a
recompute. Read endpoints power the UI; recompute re-runs the curation engine.
"""

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.config import Settings, get_settings
from app.crawl.runner import requests_used
from app.curation.engine import curate
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
    Tag,
    Track,
)
from app.db.session import get_session

router = APIRouter(prefix="/api", tags=["feed"])


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


class Facet(BaseModel):
    value: str
    label: str
    count: int


class FacetsOut(BaseModel):
    tags: list[Facet]
    labels: list[Facet]
    seed_tags: list[Facet]  # genres of your own albums (for the seed-exclusion filter)


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


async def _count(session: AsyncSession, stmt) -> int:
    return (await session.execute(stmt)).scalar_one()


def _has_tag(names: list[str]):
    """EXISTS: the recommendation's album carries any of these genre tags."""
    return exists(
        select(1)
        .select_from(AlbumTag)
        .join(Tag, Tag.id == AlbumTag.tag_id)
        .where(AlbumTag.album_id == Recommendation.album_id, Tag.name.in_(names))
    )


def _apply_rec_filters(stmt, band_id_col, *, item_type, tag, exclude_tag,
                       label_id, exclude_label_id):
    """Apply the shared feed filters (item_type / tags / labels) to a query."""
    if item_type:
        stmt = stmt.where(Recommendation.item_type == item_type)
    if label_id:
        stmt = stmt.where(band_id_col.in_(label_id))
    if exclude_label_id:
        stmt = stmt.where(band_id_col.notin_(exclude_label_id))
    if tag:
        stmt = stmt.where(_has_tag(tag))          # implies albums (tracks have no tags)
    if exclude_tag:
        stmt = stmt.where(~_has_tag(exclude_tag))
    return stmt


@router.get("/stats", response_model=StatsOut)
async def stats(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> StatsOut:
    me = (await session.execute(select(Fan.id).where(Fan.is_me.is_(True)))).scalars().first()
    owned = wished = 0
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
    return StatsOut(
        recommendations=await _count(session, select(func.count()).select_from(Recommendation)),
        fans=await _count(session, select(func.count()).select_from(Fan)),
        neighbours=await _count(
            session, select(func.count()).select_from(Fan).where(Fan.is_me.is_(False))
        ),
        albums=await _count(session, select(func.count()).select_from(Album)),
        tracks=await _count(session, select(func.count()).select_from(Track)),
        my_owned=owned,
        my_wishlist=wished,
        follows=await _count(session, select(func.count()).select_from(Follow)),
        liked=await _count(session, select(func.count()).select_from(Like)),
        requests_used=await requests_used(session),
        request_budget=settings.crawl_max_requests,
    )


@router.get("/recommendations", response_model=list[RecommendationOut])
async def recommendations(
    session: AsyncSession = Depends(get_session),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    item_type: str | None = Query(None, pattern="^(album|track)$"),
    tag: list[str] = Query(default=[]),           # filter by: album has ANY of these tags
    exclude_tag: list[str] = Query(default=[]),   # filter out: album has ANY of these tags
    label_id: list[int] = Query(default=[]),      # filter by: recommendation's band
    exclude_label_id: list[int] = Query(default=[]),
) -> list[RecommendationOut]:
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
        .order_by(Recommendation.score.desc(), Recommendation.id)
    )
    stmt = _apply_rec_filters(
        stmt, band_id_col, item_type=item_type, tag=tag, exclude_tag=exclude_tag,
        label_id=label_id, exclude_label_id=exclude_label_id,
    )
    stmt = stmt.limit(limit).offset(offset)

    rows = (await session.execute(stmt)).all()
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
        )
        for i, r in enumerate(rows)
    ]


@router.get("/recommendations/count")
async def recommendations_count(
    session: AsyncSession = Depends(get_session),
    item_type: str | None = Query(None, pattern="^(album|track)$"),
    tag: list[str] = Query(default=[]),
    exclude_tag: list[str] = Query(default=[]),
    label_id: list[int] = Query(default=[]),
    exclude_label_id: list[int] = Query(default=[]),
) -> dict[str, int]:
    """How many recommendations match the current filters (for the feed's count header)."""
    band_id_col = func.coalesce(Album.band_id, Track.band_id)
    stmt = (
        select(func.count())
        .select_from(Recommendation)
        .outerjoin(Album, Album.id == Recommendation.album_id)
        .outerjoin(Track, Track.id == Recommendation.track_id)
    )
    stmt = _apply_rec_filters(
        stmt, band_id_col, item_type=item_type, tag=tag, exclude_tag=exclude_tag,
        label_id=label_id, exclude_label_id=exclude_label_id,
    )
    return {"count": (await session.execute(stmt)).scalar_one()}


@router.get("/facets", response_model=FacetsOut)
async def facets(session: AsyncSession = Depends(get_session)) -> FacetsOut:
    """Tags and labels present in the current recommendations, with counts."""
    tag_rows = (
        await session.execute(
            select(Tag.name, func.count().label("n"))
            .select_from(Recommendation)
            .join(AlbumTag, AlbumTag.album_id == Recommendation.album_id)
            .join(Tag, Tag.id == AlbumTag.tag_id)
            .group_by(Tag.name)
            .order_by(func.count().desc(), Tag.name)
        )
    ).all()
    label_rows = (
        await session.execute(
            select(Band.id, Band.name, func.count().label("n"))
            .select_from(Recommendation)
            .outerjoin(Album, Album.id == Recommendation.album_id)
            .outerjoin(Track, Track.id == Recommendation.track_id)
            .join(Band, Band.id == func.coalesce(Album.band_id, Track.band_id))
            .group_by(Band.id, Band.name)
            .order_by(func.count().desc(), Band.name)
            .limit(200)
        )
    ).all()
    seed = await seed_tag_genres(session)
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
    exclude_seed_tag: list[str] = Query(default=[]),
) -> dict[str, Any]:
    """Recompute the feed. `exclude_seed_tag` drops recs generated from your albums
    carrying those genres (seed-provenance exclusion)."""
    scored = await curate(session, exclude_seed_tags=set(exclude_seed_tag))
    return {"computed": len(scored), "excluded_seed_tags": exclude_seed_tag}
