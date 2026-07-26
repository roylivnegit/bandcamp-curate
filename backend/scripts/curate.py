"""Compute recommendations from the crawled graph and print the top feed.

Usage:
    python -m scripts.curate [top_n]     # default 25

Recomputes the `recommendations` table (excludes owned/wishlisted/followed/
blacklisted) and prints the highest-scoring albums/tracks with their reasons.
Read-only against Bandcamp — no scraping, no credits.

Operator-only tool: curates the first `User` row's collection scan. Now that
scans are per-user, a real deployment with multiple signups should use the
`/api/recommendations/recompute` endpoint (scoped by the authenticated caller)
instead of this script.
"""

import asyncio
import sys

from sqlalchemy import select

from app.curation.engine import curate
from app.db.models import Album, Band, Track, User
from app.db.session import get_sessionmaker


async def main() -> int:
    top_n = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        user = (await session.execute(select(User).order_by(User.id))).scalars().first()
        if user is None:
            print("no users yet — sign up first (POST /api/auth/signup)")
            return 1
        scored = await curate(session, user=user)
        print(f"computed {len(scored)} recommendations; top {min(top_n, len(scored))}:\n")

        for i, s in enumerate(scored[:top_n], 1):
            if s.album_id is not None:
                row = (
                    await session.execute(
                        select(Album.title, Band.name, Album.url)
                        .join(Band, Band.id == Album.band_id, isouter=True)
                        .where(Album.id == s.album_id)
                    )
                ).first()
                title, band, url = row or ("?", None, None)
                kind = "album"
            else:
                row = (
                    await session.execute(
                        select(Track.title, Band.name, Track.url)
                        .join(Band, Band.id == Track.band_id, isouter=True)
                        .where(Track.id == s.track_id)
                    )
                ).first()
                title, band, url = row or ("?", None, None)
                kind = "track"

            r = s.reasons
            bits = [f"co_owners={r.get('co_owners', 0)}"]
            if r.get("matched_tags"):
                bits.append("tags=" + ",".join(r["matched_tags"][:4]))
            print(f"{i:2}. [{s.score:6.2f}] {kind:5} {title or '?'} — {band or '?'}")
            print(f"      {'; '.join(bits)}")
            if url:
                print(f"      {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
