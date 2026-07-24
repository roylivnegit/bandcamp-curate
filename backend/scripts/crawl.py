"""Seed and run a crawl in-process (no Redis) — for local dev and smoke testing.

Usage:
    python -m scripts.crawl seed                 # enqueue BANDCAMP_FAN_URL
    python -m scripts.crawl run [max_iters]      # drain the frontier (spends credits!)
    python -m scripts.crawl status               # frontier counts by status

Each `run` fetches live pages through the ScraperGateway and costs Nimble credits,
so it's bounded by `max_iters` (default 5). The ARQ worker (`app.worker`) is the
production path; this is the manual equivalent.
"""

import asyncio
import sys

from sqlalchemy import func, select

from app.config import get_settings
from app.crawl import runner
from app.crawl.seed import seed_fan_collection
from app.crawl.service import build_pagination_clients
from app.db.models import CrawlFrontier
from app.db.session import get_sessionmaker
from app.scraping.factory import build_gateway


async def cmd_seed() -> int:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        url = await seed_fan_collection(session)
    print(f"seeded FAN_COLLECTION: {url}")
    return 0


async def cmd_run(max_iters: int) -> int:
    settings = get_settings()
    if not settings.nimble_api_key:
        print("NIMBLE_API_KEY not set. Aborting (live crawl needs it).")
        return 2
    sessionmaker = get_sessionmaker()
    gateway = build_gateway(settings, sessionmaker=sessionmaker)
    col, fol, sup = build_pagination_clients(
        gateway, via_nimble=settings.pagination_via_nimble
    )
    outcomes = await runner.run_until_empty(
        sessionmaker, gateway, seed_url=settings.bandcamp_fan_url,
        collection_client=col, follows_client=fol, supporters_client=sup,
        max_depth=settings.crawl_max_depth, max_requests=settings.crawl_max_requests,
        max_iterations=max_iters,
    )
    for o in outcomes:
        print(f"  {o.kind:16} {o.url}  items={o.items} tracks={o.tracks} "
              f"supporters={o.supporters} enqueued={o.enqueued}")
    print(f"processed {len(outcomes)} {'entry' if len(outcomes) == 1 else 'entries'}")
    return 0


async def cmd_status() -> int:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        rows = (
            await session.execute(
                select(CrawlFrontier.status, CrawlFrontier.kind, func.count())
                .group_by(CrawlFrontier.status, CrawlFrontier.kind)
            )
        ).all()
    if not rows:
        print("frontier empty")
    for status, kind, count in rows:
        print(f"  {status:12} {kind:16} {count}")
    return 0


async def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "seed":
        return await cmd_seed()
    if cmd == "run":
        max_iters = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        return await cmd_run(max_iters)
    if cmd == "status":
        return await cmd_status()
    print(f"unknown command: {cmd}")
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
