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

Existing rows are backfilled onto the operator's own collection scan — the walk
they came from — and `scan_id` is then locked NOT NULL. Every entry has an owner:
a row nobody owns is a row no query reaches and nothing reports, which is how
11.5k entries sat unnoticed for two weeks in the first place. If rows exist and no
collection scan does, this ABORTS rather than leave them ownerless (same call as
0008: a failed migration you can fix beats silent invisible data).

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


def _drop_unique(batch, table: str, columns: list[str]) -> None:  # noqa: ANN001
    """Drop the unique over exactly `columns`, via the batch op so SQLite (which
    cannot ALTER a constraint in place) rebuilds the table instead of failing."""
    found = _find_unique(table, columns)
    if found is None:
        return
    name, kind = found
    if kind == "constraint":
        batch.drop_constraint(name, type_="unique")
    else:
        batch.drop_index(name)


def _legacy_owner_id() -> int | None:
    """The scan to hand pre-existing rows to: the earliest collection scan, i.e.
    the operator's own "My collection". Those entries were discovered by walking
    that collection, so it is their true owner, not a synthetic placeholder."""
    row = op.get_bind().execute(
        sa.text("SELECT id FROM scans WHERE kind = 'collection' ORDER BY id LIMIT 1")
    ).first()
    return row[0] if row else None


def upgrade() -> None:
    if _has_column(_TABLE, "scan_id"):
        return  # fresh DB built from ORM metadata, or already migrated

    bind = op.get_bind()
    existing = bind.execute(sa.text(f"SELECT COUNT(*) FROM {_TABLE}")).scalar_one()
    owner_id = _legacy_owner_id()
    if existing and owner_id is None:
        raise RuntimeError(
            f"{existing} crawl_frontier rows exist but there is no collection scan "
            "to attach them to. Every entry must have an owner — an unowned row is "
            "reachable by no query and reported by nothing. Create the operator's "
            "collection scan (sign up / run a collection scan), or delete these "
            "rows if the backlog is not worth keeping, then re-run."
        )

    # ONE batch block for the column, the constraint swap and the FK. SQLite can't
    # ALTER any of those in place — batch mode rebuilds the table around them — and
    # splitting them across blocks (or doing some outside) breaks there. Postgres
    # runs the same ops directly, so this stays portable rather than just claiming to.
    with op.batch_alter_table(_TABLE) as batch:
        batch.add_column(sa.Column("scan_id", sa.Integer(), nullable=True))

    if existing:
        bind.execute(
            sa.text(f"UPDATE {_TABLE} SET scan_id = :owner WHERE scan_id IS NULL"),
            {"owner": owner_id},
        )

    with op.batch_alter_table(_TABLE) as batch:
        batch.alter_column("scan_id", existing_type=sa.Integer(), nullable=False)
        _drop_unique(batch, _TABLE, _OLD_UNIQUE)
        batch.create_unique_constraint(_NEW_NAME, _NEW_UNIQUE)
        batch.create_foreign_key(f"fk_{_TABLE}_scan_id", "scans", ["scan_id"], ["id"])

    op.create_index(f"ix_{_TABLE}_scan_id", _TABLE, ["scan_id"])


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
    op.drop_index(f"ix_{_TABLE}_scan_id", table_name=_TABLE)
    with op.batch_alter_table(_TABLE) as batch:
        _drop_unique(batch, _TABLE, _NEW_UNIQUE)
        batch.drop_column("scan_id")
        batch.create_unique_constraint("uq_frontier_url_kind", _OLD_UNIQUE)
