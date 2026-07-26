"""Likes API (M5): mark a recommendation as liked/acted-on (wishlisted, followed,
bought…). A like removes the item from the feed immediately and keeps it out of
future recommendations — a positive dismissal, distinct from a band-level block.
Your next collection crawl will reflect the real action (wishlist/purchase/follow).
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import get_current_user
from app.db.models import Album, Band, Like, Recommendation, Scan, Track, User
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


async def _like_rows(session: AsyncSession, user_id: int) -> list[LikeOut]:
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
            .where(Like.user_id == user_id)
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
async def list_likes(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[LikeOut]:
    return await _like_rows(session, current_user.id)


@router.post("", response_model=LikeOut)
async def like(
    payload: LikeIn,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> LikeOut:
    item_type = str(ItemType.ALBUM if payload.album_id is not None else ItemType.TRACK)
    existing = (
        await session.execute(
            select(Like).where(
                Like.user_id == current_user.id,
                Like.item_type == item_type,
                Like.album_id == payload.album_id,
                Like.track_id == payload.track_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            Like(
                user_id=current_user.id, item_type=item_type,
                album_id=payload.album_id, track_id=payload.track_id,
            )
        )
    # Drop the whole band from the current feed immediately (curation excludes the
    # liked item's band, so keep the live feed consistent — not just this one item).
    # Scoped to the current user's OWN scans — liking is per-tenant.
    if payload.album_id is not None:
        band_id = (
            await session.execute(select(Album.band_id).where(Album.id == payload.album_id))
        ).scalar_one_or_none()
    else:
        band_id = (
            await session.execute(select(Track.band_id).where(Track.id == payload.track_id))
        ).scalar_one_or_none()
    user_scan_ids = select(Scan.id).where(Scan.user_id == current_user.id)
    if band_id is not None:
        album_ids = select(Album.id).where(Album.band_id == band_id)
        track_ids = select(Track.id).where(Track.band_id == band_id)
        await session.execute(
            delete(Recommendation).where(
                Recommendation.scan_id.in_(user_scan_ids),
                Recommendation.album_id.in_(album_ids) | Recommendation.track_id.in_(track_ids),
            )
        )
    else:  # no band — fall back to pruning just the item
        await session.execute(
            delete(Recommendation).where(
                Recommendation.scan_id.in_(user_scan_ids),
                Recommendation.album_id == payload.album_id,
                Recommendation.track_id == payload.track_id,
            )
        )
    await session.commit()
    rows = await _like_rows(session, current_user.id)
    match = next(
        (r for r in rows if r.album_id == payload.album_id and r.track_id == payload.track_id),
        None,
    )
    if match is None:  # pragma: no cover - shouldn't happen
        raise HTTPException(status_code=500, detail="like not persisted")
    return match


@router.post("/unlike")
async def unlike(
    payload: LikeIn,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    existing = (
        await session.execute(
            select(Like).where(
                Like.user_id == current_user.id,
                Like.album_id == payload.album_id, Like.track_id == payload.track_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        raise HTTPException(status_code=404, detail="not liked")
    await session.delete(existing)
    await session.commit()
    return {"unliked": True}
