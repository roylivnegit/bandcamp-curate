import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api import auth, blacklist, collection, feed, health, likes, scans
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
    if not settings.cors_origins:
        logger.warning("FRONTEND_ORIGIN is empty — every cross-origin request will be blocked.")
    yield


app = FastAPI(
    title="crate-digger",
    version="0.1.0",
    summary="Bandcamp discovery engine",
    lifespan=lifespan,
)

# There is no proxy in front of uvicorn to do this (see backend/Dockerfile), and
# `/api/collection` returns a whole collection as very repetitive JSON — 49 KB
# measured down to 2.6 KB. Added before the CORS block so CORS stays outermost:
# `add_middleware` inserts at index 0, so the last one added wraps the rest.
app.add_middleware(GZipMiddleware, minimum_size=1000)

# The deployed React app's origin (defaults to the Vite dev server locally).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)  # /api/auth (signup/login/me)
app.include_router(feed.router)  # /api/stats, /api/recommendations, /api/facets, /recompute
app.include_router(blacklist.router)  # /api/blacklist (list/block/unblock)
app.include_router(likes.router)  # /api/likes (like/list/unlike)
app.include_router(scans.router)  # /api/scans (list/create/get/run/delete)
app.include_router(collection.router)  # /api/collection (owned/wishlist/liked)
# No route serves HTML: the frontend is a separate React app (see frontend/),
# deployed on its own origin and talking to this service as a JSON API. GET /
# is intentionally a 404 here.
# Later milestones: rules, jobs, usage.


@app.get("/api/info", tags=["root"])
async def info() -> dict:
    return {"name": "crate-digger", "docs": "/docs", "health": "/health"}
