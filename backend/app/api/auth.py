"""Auth API: signup (invite-gated), login, and the current-user endpoint.

Signup creates the user's collection scan (`scan_service.create_collection_scan`)
but does not crawl anything itself — that happens once the local crawl worker's
`poll_scans` cron picks up the queued scan (see `app/crawl/scan_service.run_scan`'s
collection-kind branch).
"""

import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import create_access_token, get_current_user, hash_password, verify_password
from app.config import Settings, get_settings
from app.crawl.scan_service import create_collection_scan
from app.db.models import Scan, User
from app.db.session import get_session
from app.enums import ScanKind

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SignupIn(BaseModel):
    username: str
    password: str
    bandcamp_fan_url: str
    invite_code: str


class LoginIn(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class CollectionScanOut(BaseModel):
    id: int
    status: str


class MeOut(BaseModel):
    id: int
    username: str
    bandcamp_fan_url: str | None
    has_crawled: bool  # whether fan_id is set — collection has been ingested at least once
    collection_scan: CollectionScanOut | None


@router.post("/signup", response_model=TokenOut, status_code=201)
async def signup(
    payload: SignupIn,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TokenOut:
    if not settings.auth_invite_code:
        raise HTTPException(status_code=403, detail="signup is currently disabled")
    if not secrets.compare_digest(payload.invite_code, settings.auth_invite_code):
        raise HTTPException(status_code=403, detail="invalid invite code")

    username = payload.username.strip()
    if not username or not payload.password:
        raise HTTPException(status_code=400, detail="username and password are required")
    if not payload.bandcamp_fan_url.strip():
        raise HTTPException(status_code=400, detail="bandcamp_fan_url is required")

    existing = (
        await session.execute(select(User).where(User.username == username))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="username is already taken")

    try:
        password_hash = hash_password(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid password: {exc}") from exc

    user = User(
        username=username,
        password_hash=password_hash,
        bandcamp_fan_url=payload.bandcamp_fan_url.strip(),
    )
    session.add(user)
    await session.flush()
    await create_collection_scan(session, user)
    await session.commit()

    return TokenOut(access_token=create_access_token(user.id, settings))


@router.post("/login", response_model=TokenOut)
async def login(
    payload: LoginIn,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TokenOut:
    invalid = HTTPException(status_code=401, detail="invalid username or password")
    user = (
        await session.execute(select(User).where(User.username == payload.username.strip()))
    ).scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise invalid
    return TokenOut(access_token=create_access_token(user.id, settings))


@router.get("/me", response_model=MeOut)
async def me(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MeOut:
    scan = (
        await session.execute(
            select(Scan).where(
                Scan.user_id == current_user.id, Scan.kind == str(ScanKind.COLLECTION)
            )
        )
    ).scalars().first()
    return MeOut(
        id=current_user.id,
        username=current_user.username,
        bandcamp_fan_url=current_user.bandcamp_fan_url,
        has_crawled=current_user.fan_id is not None,
        collection_scan=CollectionScanOut(id=scan.id, status=scan.status) if scan else None,
    )
