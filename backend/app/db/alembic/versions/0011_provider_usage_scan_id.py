"""add provider_usage.scan_id (per-user crawl budget attribution)

`crawl_max_requests`/`provider_usage` were entirely global: the budget check
counts every successful fetch ever logged, by anyone, forever. With one shared
operator that was fine; with real multi-tenancy (M8) it means one user's deep
scan can permanently starve every other user's, since the global cap never
resets and doesn't know whose credits it's spending. See CLAUDE.md "Immediate
next steps" #2.

This column is the attribution this needed: each render/pagination fetch now
carries the `scan_id` it was spent on (`FetchRequest.scan_id`, threaded
through `crawl.service`'s FetchRequest helpers), so usage can be summed per
user via `Scan.user_id` (`runner.user_requests_used`). `Settings.
crawl_max_requests_per_user` (default `None` = unbounded, unchanged behavior)
enforces it in `run_until_empty` alongside the existing global cap.

Nullable and unbacked: unlike `crawl_frontier.scan_id` (0010), there is no
"every row must have an owner" invariant here — a NULL scan_id just means
"not yet attributed" (pre-existing rows, or a fetch path not yet threaded),
and it correctly falls outside every user's own total rather than being
force-assigned to one.

Guarded like 0002-0010: a fresh DB builds this from the current ORM metadata,
so this only patches an EXISTING DB.

Revision ID: 0011_provider_usage_scan_id
Revises: 0010_frontier_per_scan
Create Date: 2026-09-02

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_provider_usage_scan_id"
down_revision: str | None = "0010_frontier_per_scan"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "provider_usage"
_COLUMN = "scan_id"


def _has_column(table: str, col: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return False
    return any(c["name"] == col for c in insp.get_columns(table))


def upgrade() -> None:
    if _has_column(_TABLE, _COLUMN):
        return  # fresh DB built from ORM metadata, or already migrated
    with op.batch_alter_table(_TABLE) as batch:
        batch.add_column(sa.Column(_COLUMN, sa.Integer(), nullable=True))
        batch.create_foreign_key(f"fk_{_TABLE}_scan_id", "scans", ["scan_id"], ["id"])
    op.create_index(f"ix_{_TABLE}_scan_id", _TABLE, [_COLUMN])


def downgrade() -> None:
    if not _has_column(_TABLE, _COLUMN):
        return
    op.drop_index(f"ix_{_TABLE}_scan_id", table_name=_TABLE)
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_column(_COLUMN)
