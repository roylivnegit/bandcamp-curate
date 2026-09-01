"""Read-only report: how much of the co-ownership signal comes from big-collection
supporters vs small ones.

Usage:
    python -m scripts.mega_supporter_stats <username> [--scan ID] [--bucket N ...]

Backlog item "Mega-supporters flatten the signal": a collector who owns 8,000 records
co-owns everything with everyone, so their vote should arguably count for less than a
200-record collector with real overlap. This measures the actual distribution first,
per the backlog's own "worth measuring before building" — it changes no scoring, does
no scraping, spends no credits.
"""

import argparse
import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.curation.engine import NEIGHBOUR_SIZE_BUCKETS, neighbour_size_report
from app.db.models import Scan, User
from app.db.session import get_sessionmaker
from app.enums import ScanKind


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


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    parser.add_argument(
        "--scan", type=int, default=None, help="scan id (default: their collection scan)"
    )
    parser.add_argument(
        "--bucket", type=int, action="append", default=None,
        help=f"repeatable bucket upper bound (default: {NEIGHBOUR_SIZE_BUCKETS})",
    )
    args = parser.parse_args()
    buckets = tuple(sorted(args.bucket)) if args.bucket else NEIGHBOUR_SIZE_BUCKETS

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
            "NOTE: bucket sizes are RECORDED fan_items counts, a lower bound — a\n"
            "neighbour's collection visit can be parked mid-crawl, so an under-crawled\n"
            "mega-collector may still show up in a smaller bucket than they belong in.\n"
        )
        rows = await neighbour_size_report(session, scan, user, buckets=buckets)
        if not rows:
            print("no neighbours for this scan yet")
            return 0
        print(
            f"{'bucket':>12} {'neighbours':>10} {'nbr%':>6} "
            f"{'votes':>7} {'vote%':>6} {'weighted%':>9}"
        )
        for r in rows:
            print(
                f"{r['bucket']:>12} {r['neighbours']:>10} {r['neighbour_share'] * 100:5.1f}% "
                f"{r['votes']:>7} {r['vote_share'] * 100:5.1f}% {r['weighted_share'] * 100:8.1f}%"
            )
        print(
            "\nA bucket whose vote% badly outruns its nbr% is dominating the raw "
            "co_owners/min_co_owners floor. If its weighted% stays close to nbr% "
            "instead, ADR-0003's overlap-with-me weighting is already correcting for "
            "it there, and the raw floor is the piece still exposed."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
