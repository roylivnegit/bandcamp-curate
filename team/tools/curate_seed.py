#!/usr/bin/env python3
"""Run the real curation engine against the freshly-loaded sandbox seed data.

team/fixtures/seed.sql inserts the raw catalog/social-graph rows but deliberately does not
hand-compute `recommendations` — scoring logic changes over time, and a hand-written score
in a SQL fixture would silently drift from what the app actually does. Instead, this calls
the same `curate()` the API itself calls, so the E2E harness always exercises the current
scoring code.

Run with the backend venv (needs the `app` package and its dependencies), with DATABASE_URL
already pointed at the sandbox:

    cd backend && .venv/bin/python3 ../team/tools/curate_seed.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from sqlalchemy import select  # noqa: E402

from app.curation.engine import curate  # noqa: E402
from app.db.models import User  # noqa: E402
from app.db.session import get_sessionmaker  # noqa: E402


async def main() -> int:
    maker = get_sessionmaker()
    async with maker() as session:
        user = (
            await session.execute(select(User).where(User.username == "e2e-tester"))
        ).scalar_one_or_none()
        if user is None:
            print("curate_seed: no e2e-tester user found — did seed.sql load?", file=sys.stderr)
            return 1
        scored = await curate(session, user=user)
        await session.commit()
        print(f"curate_seed: computed {len(scored)} recommendation(s) for e2e-tester")
        for item in scored:
            print(f"  - {item.item_type} album_id={item.album_id} track_id={item.track_id} score={item.score:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
