from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_session

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(settings: Settings = Depends(get_settings)) -> dict:
    """Liveness + config presence. Never exposes secret values."""
    return {
        "status": "ok",
        "env": settings.app_env,
        "nimble_configured": settings.nimble_configured,
        "seed_configured": bool(settings.bandcamp_fan_url),
    }


@router.get("/health/db")
async def health_db(session: AsyncSession = Depends(get_session)) -> dict:
    """Readiness: verifies a round-trip to Postgres."""
    result = await session.execute(text("SELECT 1"))
    return {"status": "ok", "db": result.scalar_one() == 1}
