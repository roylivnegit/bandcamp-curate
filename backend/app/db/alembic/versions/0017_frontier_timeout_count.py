"""add crawl_frontier.timeout_count (track timeouts separately from the
fairness-pass `attempts` counter)

`runner.process_one`'s TimeoutError handler capped retries by checking
`entry.attempts >= MAX_ENTRY_TIMEOUTS`, but `attempts` is bumped on every
`claim_next` -- including the ordinary, non-failure `mark_partial` re-page a
large collection needs several visits to fully page (p90 ~1,700 items,
PAGES_PER_VISIT=10 -> ~5 claims with zero timeouts). Once such a collection's
`attempts` passed MAX_ENTRY_TIMEOUTS from normal paging alone, its very next
genuine timeout -- even a single one -- permanently failed the entry instead
of allowing the intended number of retries, silently truncating that
collection's crawl.

This column decouples the two: incremented only in the TimeoutError path,
reset to 0 by `mark_done`/`mark_partial` (real progress), so it counts
consecutive timeouts specifically rather than claims of any kind.

Guarded like 0002-0016: a fresh DB builds this from the current ORM metadata,
so this only patches an EXISTING DB.

Revision ID: 0017_frontier_timeout_count
Revises: 0016_login_lockout
Create Date: 2026-09-04

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_frontier_timeout_count"
down_revision: str | None = "0016_login_lockout"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "crawl_frontier"
_COLUMN = "timeout_count"


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
