"""Scans API (M7 Stage 2): list scans, create one from seed URLs (queued for the
Mac poller to run), inspect, re-run, and delete. The feed endpoints take a
`scan_id` to scope recommendations to a scan.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import get_current_user
from app.crawl.scan_service import create_scan
from app.db.models import Recommendation, Scan, ScanSeed, User
from app.db.session import get_session
from app.enums import ScanKind, ScanStatus

router = APIRouter(prefix="/api/scans", tags=["scans"])


class ScanCreateIn(BaseModel):
    name: str
    seeds: list[str]


class SeedOut(BaseModel):
    url: str
    seed_type: str
    resolved_album_id: int | None = None
    resolved_track_id: int | None = None


class ScanOut(BaseModel):
    id: int
    name: str
    kind: str
    status: str
    error: str | None = None
    seed_count: int
    rec_count: int
    last_run_at: datetime | None = None
    stats: dict = {}


class ScanDetailOut(ScanOut):
    seeds: list[SeedOut] = []


def _seed_count():
    return (
        select(func.count()).select_from(ScanSeed)
        .where(ScanSeed.scan_id == Scan.id).scalar_subquery()
    )


def _rec_count():
    return (
        select(func.count()).select_from(Recommendation)
        .where(Recommendation.scan_id == Scan.id).scalar_subquery()
    )


def _to_out(scan: Scan, seed_count: int, rec_count: int) -> ScanOut:
    return ScanOut(
        id=scan.id, name=scan.name, kind=scan.kind, status=scan.status,
        error=scan.error, seed_count=seed_count, rec_count=rec_count,
        last_run_at=scan.last_run_at, stats=scan.stats or {},
    )


async def _detail(session: AsyncSession, scan_id: int, user_id: int) -> ScanDetailOut:
    scan = await session.get(Scan, scan_id)
    if scan is None or scan.user_id != user_id:
        raise HTTPException(status_code=404, detail="scan not found")
    seeds = (
        await session.execute(select(ScanSeed).where(ScanSeed.scan_id == scan_id))
    ).scalars().all()
    recs = (
        await session.execute(
            select(func.count()).select_from(Recommendation)
            .where(Recommendation.scan_id == scan_id)
        )
    ).scalar_one()
    base = _to_out(scan, len(seeds), recs)
    return ScanDetailOut(
        **base.model_dump(),
        seeds=[
            SeedOut(url=s.url, seed_type=s.seed_type,
                    resolved_album_id=s.resolved_album_id,
                    resolved_track_id=s.resolved_track_id)
            for s in seeds
        ],
    )


@router.get("", response_model=list[ScanOut])
async def list_scans(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[ScanOut]:
    rows = (
        await session.execute(
            select(Scan, _seed_count().label("sc"), _rec_count().label("rc"))
            .where(Scan.user_id == current_user.id)
            .order_by(Scan.id)
        )
    ).all()
    return [_to_out(scan, sc, rc) for scan, sc, rc in rows]


@router.post("", response_model=ScanDetailOut, status_code=201)
async def create(
    payload: ScanCreateIn,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ScanDetailOut:
    try:
        scan = await create_scan(session, current_user.id, payload.name, payload.seeds)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return await _detail(session, scan.id, current_user.id)


@router.get("/{scan_id}", response_model=ScanDetailOut)
async def get_scan(
    scan_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ScanDetailOut:
    return await _detail(session, scan_id, current_user.id)


@router.post("/{scan_id}/run", response_model=ScanDetailOut)
async def run_scan(
    scan_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ScanDetailOut:
    """Re-queue a scan for the poller (re-crawl its seeds + recompute)."""
    scan = await session.get(Scan, scan_id)
    if scan is None or scan.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="scan not found")
    scan.status = str(ScanStatus.QUEUED)
    scan.error = None
    await session.commit()
    return await _detail(session, scan_id, current_user.id)


@router.delete("/{scan_id}")
async def delete_scan(
    scan_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    scan = await session.get(Scan, scan_id)
    if scan is None or scan.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="scan not found")
    if scan.kind == str(ScanKind.COLLECTION):
        raise HTTPException(status_code=400, detail="the collection scan can't be deleted")
    # Explicitly drop this scan's recs (portable across SQLite/PG); seeds go via
    # the ORM relationship cascade.
    await session.execute(delete(Recommendation).where(Recommendation.scan_id == scan_id))
    await session.delete(scan)
    await session.commit()
    return {"deleted": scan_id}
