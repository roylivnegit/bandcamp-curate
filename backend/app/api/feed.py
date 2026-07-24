"""Feed API (M5): read the ranked recommendations + a stats summary, and trigger a
recompute. Read endpoints power the UI; recompute re-runs the curation engine.
"""

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.config import Settings, get_settings
from app.crawl.runner import requests_used
from app.curation.engine import curate
from app.db.models import (
    Album,
    Band,
    Fan,
    FanItem,
    Follow,
    Recommendation,
    Track,
)
from app.db.session import get_session

router = APIRouter(prefix="/api", tags=["feed"])


class Reasons(BaseModel):
    co_owners: int = 0
    tag_affinity: float = 0.0
    matched_tags: list[str] = []


class RecommendationOut(BaseModel):
    rank: int
    item_type: str
    score: float
    title: str | None
    band_name: str | None
    url: str | None
    reasons: Reasons


class StatsOut(BaseModel):
    recommendations: int
    fans: int
    neighbours: int
    albums: int
    tracks: int
    my_owned: int
    my_wishlist: int
    follows: int
    requests_used: int
    request_budget: int


async def _count(session: AsyncSession, stmt) -> int:
    return (await session.execute(stmt)).scalar_one()


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
        requests_used=await requests_used(session),
        request_budget=settings.crawl_max_requests,
    )


@router.get("/recommendations", response_model=list[RecommendationOut])
async def recommendations(
    session: AsyncSession = Depends(get_session),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    item_type: str | None = Query(None, pattern="^(album|track)$"),
) -> list[RecommendationOut]:
    ab = aliased(Band)
    tb = aliased(Band)
    stmt = (
        select(
            Recommendation.item_type,
            Recommendation.score,
            Recommendation.reasons,
            func.coalesce(Album.title, Track.title).label("title"),
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
    if item_type:
        stmt = stmt.where(Recommendation.item_type == item_type)
    stmt = stmt.limit(limit).offset(offset)

    rows = (await session.execute(stmt)).all()
    return [
        RecommendationOut(
            rank=offset + i + 1,
            item_type=r.item_type,
            score=round(r.score, 2),
            title=r.title,
            band_name=r.band_name,
            url=r.url,
            reasons=Reasons(**(r.reasons or {})),
        )
        for i, r in enumerate(rows)
    ]


@router.post("/recommendations/recompute")
async def recompute(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    scored = await curate(session)
    return {"computed": len(scored)}
