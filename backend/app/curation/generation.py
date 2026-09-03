"""Shared helper for bumping `scans.recompute_generation` outside the normal
curate()/store_recommendations() path.

`/api/recommendations` and `/api/facets` key their conditional-GET ETag on a
scan's `recompute_generation` (migration 0013): unchanged generation means a
client's cached response is still valid, so the server can return a 304
without re-sending the same rows. `store_recommendations` bumps it on every
real re-curate — but block/unblock/like/unlike prune (or would re-surface)
`Recommendation` rows directly, for a feed that updates the instant you act,
without going through curate() at all. Skip the bump there and a client's
already-cached ETag for that scan looks unchanged even though the rows
underneath it did — a block from your phone doesn't just take a moment to
reach another already-open tab, it never does, because that tab keeps
getting served its stale cached copy on every subsequent visit too.
"""

from sqlalchemy import Select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Scan


async def bump_generations(session: AsyncSession, scan_ids: Select) -> None:
    """Bump `recompute_generation` for every scan in `scan_ids` (a scalar
    subquery, e.g. `select(Scan.id).where(Scan.user_id == ...)`). Callers
    still need their own `session.commit()` — this only stages the update."""
    await session.execute(
        update(Scan)
        .where(Scan.id.in_(scan_ids))
        .values(recompute_generation=Scan.recompute_generation + 1)
    )
