"""Password hashing, JWT issuance/verification, and the `get_current_user`
dependency every protected route depends on.

The JWT signing key is `settings.auth_secret_key` — read the same way as
`NIMBLE_API_KEY` (see app/config.py): never logged, never serialized.
"""

from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import User
from app.db.session import get_session

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE = timedelta(days=30)

_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """Raises ValueError for a >72-byte password (bcrypt's own limit) — callers
    should turn that into a clean 400, not a 500."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: int, settings: Settings) -> str:
    now = datetime.now(UTC)
    payload = {"sub": str(user_id), "iat": now, "exp": now + ACCESS_TOKEN_EXPIRE}
    return jwt.encode(payload, settings.auth_secret_key, algorithm=ALGORITHM)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    try:
        payload = jwt.decode(
            credentials.credentials, settings.auth_secret_key, algorithms=[ALGORITHM]
        )
    except jwt.InvalidTokenError as exc:
        raise unauthorized from exc
    user_id = payload.get("sub")
    if user_id is None:
        raise unauthorized
    user = await session.get(User, int(user_id))
    if user is None:
        raise unauthorized
    return user
