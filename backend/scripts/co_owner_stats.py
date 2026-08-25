"""Read-only histogram: how the feed's length changes as `min_co_owners` rises.

Usage:
    python -m scripts.co_owner_stats <username> [floor ...]

For each candidate floor, calls `compute_recommendations` with that floor and
prints how many recommendations survive. Lets Roy pick a floor from data
instead of a guess. Never writes: no `store_recommendations`, no scan
creation, no scraping, no credits.
"""

import argparse
import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.curation.engine import compute_recommendations
from app.db.models import Scan, User
from app.db.session import get_sessionmaker
from app.enums import ScanKind

DEFAULT_FLOORS = [1, 2, 3, 5, 8]


async def resolve_user(session: AsyncSession, username: str) -> User | None:
    return (
        await session.execute(select(User).where(User.username == username))
    ).scalar_one_or_none()


async def resolve_scan(session: AsyncSession, user: User, scan_id: int | None) -> Scan | None:
    """The user's collection scan, or the given `scan_id` iff it is theirs."""
    if scan_id is not None:
        scan = await session.get(Scan, scan_id)
        return scan if scan is not None and scan.user_id == user.id else None
    return (
        await session.execute(
            select(Scan)
            .where(Scan.user_id == user.id, Scan.kind == str(ScanKind.COLLECTION))
            .order_by(Scan.id)
        )
    ).scalars().first()


async def floor_histogram(
    session: AsyncSession, user: User, scan: Scan, floors: list[int]
) -> list[dict]:
    """Feed length at each candidate floor. Read-only — never writes."""
    rows = []
    for floor in sorted(set(floors)):
        stats: dict = {}
        scored = await compute_recommendations(
            session, scan, user, min_co_owners=floor, stats_out=stats
        )
        rows.append({
            "floor": floor,
            "count": len(scored),
            "candidates": stats["candidates"],
            "filtered_by_floor": stats["filtered_by_floor"],
        })
        print(
            f"floor >= {floor:>3}: {len(scored):5} recs  "
            f"(candidates={stats['candidates']}, filtered_by_floor={stats['filtered_by_floor']})"
        )
    return rows


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    parser.add_argument(
        "--scan", type=int, default=None, help="scan id (default: their collection scan)"
    )
    parser.add_argument("--floor", type=int, action="append", default=None, help="repeatable")
    args = parser.parse_args()
    floors = args.floor or DEFAULT_FLOORS

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        user = await resolve_user(session, args.username)
        if user is None:
            print(f"no such user: {args.username}")
            return 1
        scan = await resolve_scan(session, user, args.scan)
        if scan is None:
            print(
                f"no scan for {args.username} (scan_id={args.scan}) — "
                "run their collection crawl first"
            )
            return 1
        print(
            "NOTE: co-owner counts reflect crawl progress, not final taste — collections page\n"
            "10 items at a time and resume later, so a floor picked mid-crawl reads stricter\n"
            "than the same floor will once the crawl completes.\n"
        )
        await floor_histogram(session, user, scan, floors)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
