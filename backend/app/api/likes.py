"""Likes API (M5): mark a recommendation as liked/acted-on (wishlisted, followed,
bought…). A like removes the item from the feed immediately and keeps it out of
future recommendations — a positive dismissal, distinct from a band-level block.
Your next collection crawl will reflect the real action (wishlist/purchase/follow).
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Album, Band, Like, Recommendation, Track
from app.db.session import get_session
from app.enums import ItemType

router = APIRouter(prefix="/api/likes", tags=["likes"])


class LikeIn(BaseModel):
    album_id: int | None = None
    track_id: int | None = None

    @model_validator(mode="after")
    def _one_of(self) -> "LikeIn":
        if (self.album_id is None) == (self.track_id is None):
            raise ValueError("exactly one of album_id / track_id is required")
        return self


class LikeOut(BaseModel):
    id: int
    item_type: str
    album_id: int | None
    track_id: int | None
    title: str | None
    band_name: str | None
    url: str | None


async def _like_rows(session: AsyncSession) -> list[LikeOut]:
    ab = Band.__table__.alias("ab")
    tb = Band.__table__.alias("tb")
    rows = (
        await session.execute(
            select(
                Like.id, Like.item_type, Like.album_id, Like.track_id,
                Album.title, Track.title, ab.c.name, tb.c.name, Album.url, Track.url,
            )
            .select_from(Like)
            .outerjoin(Album, Album.id == Like.album_id)
            .outerjoin(Track, Track.id == Like.track_id)
            .outerjoin(ab, ab.c.id == Album.band_id)
            .outerjoin(tb, tb.c.id == Track.band_id)
            .order_by(Like.id.desc())
        )
    ).all()
    return [
        LikeOut(
            id=i, item_type=it, album_id=aid, track_id=tid,
            title=at or tt, band_name=abn or tbn, url=au or tu,
        )
        for i, it, aid, tid, at, tt, abn, tbn, au, tu in rows
    ]


@router.get("", response_model=list[LikeOut])
async def list_likes(session: AsyncSession = Depends(get_session)) -> list[LikeOut]:
    return await _like_rows(session)


@router.post("", response_model=LikeOut)
async def like(payload: LikeIn, session: AsyncSession = Depends(get_session)) -> LikeOut:
    item_type = str(ItemType.ALBUM if payload.album_id is not None else ItemType.TRACK)
    existing = (
        await session.execute(
            select(Like).where(
                Like.item_type == item_type,
                Like.album_id == payload.album_id,
                Like.track_id == payload.track_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            Like(item_type=item_type, album_id=payload.album_id, track_id=payload.track_id)
        )
    # Drop it from the current feed immediately.
    await session.execute(
        delete(Recommendation).where(
            Recommendation.album_id == payload.album_id,
            Recommendation.track_id == payload.track_id,
        )
    )
    await session.commit()
    rows = await _like_rows(session)
    match = next(
        (r for r in rows if r.album_id == payload.album_id and r.track_id == payload.track_id),
        None,
    )
    if match is None:  # pragma: no cover - shouldn't happen
        raise HTTPException(status_code=500, detail="like not persisted")
    return match


@router.post("/unlike")
async def unlike(payload: LikeIn, session: AsyncSession = Depends(get_session)) -> dict:
    result = await session.execute(
        delete(Like).where(Like.album_id == payload.album_id, Like.track_id == payload.track_id)
    )
    await session.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="not liked")
    return {"unliked": True}
