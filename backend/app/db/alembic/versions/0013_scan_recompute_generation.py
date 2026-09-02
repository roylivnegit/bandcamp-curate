"""add scans.recompute_generation (tag a feed page with the generation it was
computed under)

`crawl_curate_each_slice` does a wholesale clear+insert of `recommendations`
inside one transaction every time a scan re-curates, and the React feed
re-fetches page 0 whenever `stats.recommendations` (the total count) moves.
But a recompute that swaps one item out for another — or just re-ranks ties —
leaves the total count unchanged, so a user who has paged past page 0 with
offset/limit can see items shift, repeat, or vanish between requests: their
already-rendered rows and the next `loadMore` page can belong to two
different rankings with nothing telling them apart. See team/memory/backlog.md
"The feed can silently reflow under a user who's mid-scroll".

This column is that "which ranking is this" tag. `curation.engine.
store_recommendations` bumps it on every call (the one place every re-curate
path already goes through), so it changes strictly more often than the total
count does. `GET /api/scans/{id}` and `GET /api/recommendations` both return
it; the frontend re-arms its page-0 reload on this instead of the total count
and shows a "list updated" note when the reload actually changed the ranking
underneath an already-scrolled reader.

Persisted rather than an in-process counter: slices are re-curated from ARQ
worker processes distinct from the API process, so a module-level int would
desync between them.

Guarded like 0002-0012: a fresh DB builds this from the current ORM metadata,
so this only patches an EXISTING DB.

Revision ID: 0013_scan_recompute_generation
Revises: 0012_blacklist_expires_at
Create Date: 2026-09-02

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_scan_recompute_generation"
down_revision: str | None = "0012_blacklist_expires_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "scans"
_COLUMN = "recompute_generation"


def _has_column(table: str, col: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return False
    return any(c["name"] == col for c in insp.get_columns(table))


def upgrade() -> None:
    if _has_column(_TABLE, _COLUMN):
        return  # fresh DB built from ORM metadata, or already migrated
    with op.batch_alter_table(_TABLE) as batch:
        batch.add_column(
            sa.Column(_COLUMN, sa.Integer(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    if not _has_column(_TABLE, _COLUMN):
        return
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_column(_COLUMN)
