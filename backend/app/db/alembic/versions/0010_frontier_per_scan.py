"""scope crawl_frontier to a scan

The frontier was global: every scan drained one shared queue. A 2026-07-24
operator crawl left 11,521 depth-3 albums pending, and every scan created since
inherited them — a scan whose own seed was crawled in the first minute still
reported "running" a day later, working through a backlog it never asked for and
spending its owner's credits on it.

Each scan now walks its own subtree (`scan_id`), so "is this scan finished?" is a
question about its own work. The *graph* stays global — bands, albums, tracks and
supporters are shared exactly as before — and an entry whose (url, kind) another
scan already crawled completes without a fetch, replaying its fan-out from the
stored rows (`app.crawl.replay`). Isolation of scheduling, not of knowledge.

Existing rows are left at `scan_id = NULL`, meaning "legacy": no scan drains them,
and only the pre-per-scan operator chain (`scripts/crawl.py`, `seed_crawl`) can.
That keeps the discovered work — it was paid for — without any scan picking it up
by accident. Note NULLs are distinct under a unique constraint, so legacy rows are
not deduplicated against each other; they are inert, so this doesn't matter.

Guarded like 0002-0009: a fresh DB builds this from the current ORM metadata, so
this only patches an EXISTING DB.

Revision ID: 0010_frontier_per_scan
Revises: 0009_frontier_cursor
Create Date: 2026-08-06

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_frontier_per_scan"
down_revision: str | None = "0009_frontier_cursor"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "crawl_frontier"
_OLD_UNIQUE = ["url", "kind"]
_NEW_UNIQUE = ["scan_id", "url", "kind"]
_NEW_NAME = "uq_frontier_scan_url_kind"


def _has_column(table: str, col: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return False
    return any(c["name"] == col for c in insp.get_columns(table))


def _find_unique(table: str, columns: list[str]) -> tuple[str, str] | None:
    """(name, 'constraint'|'index') of a unique covering exactly these columns.
    Checks both, since a column-level unique can materialize as either."""
    insp = sa.inspect(op.get_bind())
    for uc in insp.get_unique_constraints(table):
        if uc.get("column_names") == columns:
            return uc["name"], "constraint"
    for ix in insp.get_indexes(table):
        if ix.get("unique") and ix.get("column_names") == columns:
            return ix["name"], "index"
    return None


def _drop_unique(table: str, columns: list[str]) -> None:
    found = _find_unique(table, columns)
    if found is None:
        return
    name, kind = found
    if kind == "constraint":
        op.drop_constraint(name, table, type_="unique")
    else:
        op.drop_index(name, table_name=table)


def upgrade() -> None:
    if _has_column(_TABLE, "scan_id"):
        return  # fresh DB built from ORM metadata, or already migrated

    # SQLite can't ALTER constraints in place; batch_alter_table rebuilds the table.
    with op.batch_alter_table(_TABLE) as batch:
        batch.add_column(sa.Column("scan_id", sa.Integer(), nullable=True))

    op.create_index(f"ix_{_TABLE}_scan_id", _TABLE, ["scan_id"])
    # Existing rows stay NULL — legacy, drained by nothing.
    _drop_unique(_TABLE, _OLD_UNIQUE)
    op.create_unique_constraint(_NEW_NAME, _TABLE, _NEW_UNIQUE)
    op.create_foreign_key(
        f"fk_{_TABLE}_scan_id", _TABLE, "scans", ["scan_id"], ["id"]
    )


def downgrade() -> None:
    if not _has_column(_TABLE, "scan_id"):
        return
    # Per-scan rows can collide on (url, kind) once the scope is dropped; keep the
    # lowest id per pair so the old unique can be restored.
    op.execute(
        sa.text(
            f"DELETE FROM {_TABLE} WHERE id NOT IN "
            f"(SELECT MIN(id) FROM {_TABLE} GROUP BY url, kind)"
        )
    )
    _drop_unique(_TABLE, _NEW_UNIQUE)
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_column("scan_id")
    op.create_unique_constraint("uq_frontier_url_kind", _TABLE, _OLD_UNIQUE)
