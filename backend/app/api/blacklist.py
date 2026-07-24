"""Blacklist API (M5): block a band from recommendations, list what's blocked, and
unblock. Curation already excludes active blacklist rows; blocking also prunes any
current recommendations for that band so the feed updates immediately.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Album, Band, Blacklist, Recommendation, Track
from app.db.session import get_session
from app.enums import BandKind, TargetType

router = APIRouter(prefix="/api/blacklist", tags=["blacklist"])


class BlockIn(BaseModel):
    band_id: int
    reason: str | None = None


class BlacklistOut(BaseModel):
    id: int
    band_id: int
    band_name: str | None
    band_url: str | None
    reason: str | None


@router.get("", response_model=list[BlacklistOut])
async def list_blocked(session: AsyncSession = Depends(get_session)) -> list[BlacklistOut]:
    rows = (
        await session.execute(
            select(Blacklist.id, Blacklist.band_id, Band.name, Band.url, Blacklist.reason)
            .join(Band, Band.id == Blacklist.band_id)
            .where(Blacklist.active.is_(True), Blacklist.band_id.isnot(None))
            .order_by(Band.name)
        )
    ).all()
    return [
        BlacklistOut(id=i, band_id=b, band_name=n, band_url=u, reason=r)
        for i, b, n, u, r in rows
    ]


@router.post("", response_model=BlacklistOut)
async def block(payload: BlockIn, session: AsyncSession = Depends(get_session)) -> BlacklistOut:
    band = (
        await session.execute(select(Band).where(Band.id == payload.band_id))
    ).scalar_one_or_none()
    if band is None:
        raise HTTPException(status_code=404, detail="band not found")

    entry = (
        await session.execute(select(Blacklist).where(Blacklist.band_id == band.id))
    ).scalar_one_or_none()
    target = band.kind if band.kind in (BandKind.ARTIST, BandKind.LABEL) else str(TargetType.ARTIST)
    if entry is None:
        entry = Blacklist(band_id=band.id, target_type=target, active=True, reason=payload.reason)
        session.add(entry)
    else:
        entry.active = True
        if payload.reason:
            entry.reason = payload.reason

    # Prune current recommendations for this band so the feed updates now.
    album_ids = select(Album.id).where(Album.band_id == band.id)
    track_ids = select(Track.id).where(Track.band_id == band.id)
    await session.execute(
        delete(Recommendation).where(
            Recommendation.album_id.in_(album_ids) | Recommendation.track_id.in_(track_ids)
        )
    )
    await session.flush()
    await session.commit()
    return BlacklistOut(
        id=entry.id, band_id=band.id, band_name=band.name, band_url=band.url, reason=entry.reason
    )


@router.post("/{band_id}/unblock")
async def unblock(band_id: int, session: AsyncSession = Depends(get_session)) -> dict:
    entry = (
        await session.execute(
            select(Blacklist).where(Blacklist.band_id == band_id, Blacklist.active.is_(True))
        )
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="band is not blocked")
    entry.active = False
    await session.commit()
    return {"unblocked": band_id}
