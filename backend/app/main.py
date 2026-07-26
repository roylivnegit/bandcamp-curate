import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, blacklist, feed, health, likes, scans
from app.config import get_settings

settings = get_settings()
logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("crate_digger")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("crate-digger starting (env=%s)", settings.app_env)
    if not settings.nimble_configured:
        logger.warning("NIMBLE_API_KEY is not set — scraping will fail until configured.")
    if not settings.auth_configured:
        logger.warning("AUTH_SECRET_KEY is not set — auth tokens can't be issued/verified.")
    yield


app = FastAPI(
    title="crate-digger",
    version="0.1.0",
    summary="Bandcamp discovery engine",
    lifespan=lifespan,
)

# The deployed React app's origin (defaults to the Vite dev server locally).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)  # /api/auth (signup/login/me)
app.include_router(feed.router)  # /api/stats, /api/recommendations, /api/facets, /recompute
app.include_router(blacklist.router)  # /api/blacklist (list/block/unblock)
app.include_router(likes.router)  # /api/likes (like/list/unlike)
app.include_router(scans.router)  # /api/scans (list/create/get/run/delete)
# NOTE: app/api/ui.py (the old server-rendered feed at GET /) is deliberately NOT
# registered. Its fetch() calls are unauthenticated, so every one of them 401s now
# that routes require a bearer token — it would load and then silently fail, which
# is worse than a clean 404. The React frontend replaces it; the file is kept for
# reference until that lands, then removed.
# Later milestones: rules, jobs, usage.


@app.get("/api/info", tags=["root"])
async def info() -> dict:
    return {"name": "crate-digger", "docs": "/docs", "health": "/health"}
