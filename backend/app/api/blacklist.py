"""Blacklist API (M5): block a band from recommendations, list what's blocked, and
unblock. Curation already excludes active blacklist rows; blocking also prunes any
current recommendations for that band so the feed updates immediately.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import get_current_user
from app.db.models import Album, Band, Blacklist, Recommendation, Scan, Track, User
from app.db.session import get_session
from app.enums import BandKind, TargetType

router = APIRouter(prefix="/api/blacklist", tags=["blacklist"])


class BlockIn(BaseModel):
    band_id: int
    reason: str | None = None
    expires_at: datetime | None = None
    """Optional "not now" — omit to block indefinitely, as before."""


class BlacklistOut(BaseModel):
    id: int
    band_id: int
    band_name: str | None
    band_url: str | None
    reason: str | None
    expires_at: datetime | None


@router.get("", response_model=list[BlacklistOut])
async def list_blocked(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[BlacklistOut]:
    rows = (
        await session.execute(
            select(
                Blacklist.id, Blacklist.band_id, Band.name, Band.url,
                Blacklist.reason, Blacklist.expires_at,
            )
            .join(Band, Band.id == Blacklist.band_id)
            .where(
                Blacklist.user_id == current_user.id,
                Blacklist.active.is_(True),
                Blacklist.band_id.isnot(None),
                or_(Blacklist.expires_at.is_(None), Blacklist.expires_at > datetime.now(UTC)),
            )
            .order_by(Band.name)
        )
    ).all()
    return [
        BlacklistOut(id=i, band_id=b, band_name=n, band_url=u, reason=r, expires_at=e)
        for i, b, n, u, r, e in rows
    ]


@router.post("", response_model=BlacklistOut)
async def block(
    payload: BlockIn,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> BlacklistOut:
    band = (
        await session.execute(select(Band).where(Band.id == payload.band_id))
    ).scalar_one_or_none()
    if band is None:
        raise HTTPException(status_code=404, detail="band not found")

    entry = (
        await session.execute(
            select(Blacklist).where(
                Blacklist.user_id == current_user.id, Blacklist.band_id == band.id
            )
        )
    ).scalar_one_or_none()
    target = band.kind if band.kind in (BandKind.ARTIST, BandKind.LABEL) else str(TargetType.ARTIST)
    if entry is None:
        entry = Blacklist(
            user_id=current_user.id, band_id=band.id, target_type=target,
            active=True, reason=payload.reason, expires_at=payload.expires_at,
        )
        session.add(entry)
    else:
        entry.active = True
        entry.expires_at = payload.expires_at
        if payload.reason:
            entry.reason = payload.reason

    # Prune this band's recs from the current user's OWN scans only — blocking
    # is per-user and must never touch another tenant's feed.
    album_ids = select(Album.id).where(Album.band_id == band.id)
    track_ids = select(Track.id).where(Track.band_id == band.id)
    user_scan_ids = select(Scan.id).where(Scan.user_id == current_user.id)
    await session.execute(
        delete(Recommendation).where(
            Recommendation.scan_id.in_(user_scan_ids),
            Recommendation.album_id.in_(album_ids) | Recommendation.track_id.in_(track_ids),
        )
    )
    await session.flush()
    await session.commit()
    return BlacklistOut(
        id=entry.id, band_id=band.id, band_name=band.name, band_url=band.url,
        reason=entry.reason, expires_at=entry.expires_at,
    )


@router.post("/{band_id}/unblock")
async def unblock(
    band_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    entry = (
        await session.execute(
            select(Blacklist).where(
                Blacklist.user_id == current_user.id,
                Blacklist.band_id == band_id,
                Blacklist.active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="band is not blocked")
    entry.active = False
    await session.commit()
    return {"unblocked": band_id}
