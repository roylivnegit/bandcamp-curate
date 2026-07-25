import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import blacklist, feed, health, likes, scans, ui
from app.config import get_settings

settings = get_settings()
logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("crate_digger")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("crate-digger starting (env=%s)", settings.app_env)
    if not settings.nimble_configured:
        logger.warning("NIMBLE_API_KEY is not set — scraping will fail until configured.")
    yield


app = FastAPI(
    title="crate-digger",
    version="0.1.0",
    summary="Bandcamp discovery engine",
    lifespan=lifespan,
)

# The Vite dev server; tighten for production deploys.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(feed.router)  # /api/stats, /api/recommendations, /api/facets, /recompute
app.include_router(blacklist.router)  # /api/blacklist (list/block/unblock)
app.include_router(likes.router)  # /api/likes (like/list/unlike)
app.include_router(scans.router)  # /api/scans (list/create/get/run/delete)
app.include_router(ui.router)  # GET / — the feed UI
# Later milestones: rules, jobs, usage.


@app.get("/api/info", tags=["root"])
async def info() -> dict:
    return {"name": "crate-digger", "docs": "/docs", "health": "/health", "ui": "/"}
