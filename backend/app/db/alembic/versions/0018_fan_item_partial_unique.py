"""fan_items: replace the no-op uq_fan_item with two partial unique indexes

`uq_fan_item` was a single UniqueConstraint on (fan_id, item_type, album_id,
track_id) -- but an album row always has track_id NULL and a track row always
has album_id NULL, and standard SQL treats NULL as distinct from NULL even
inside a unique constraint. So this constraint never actually rejected a
duplicate row (verified empirically: two identical album FanItem rows both
insert without error). `_add_fan_item`/`_add_edge_or_false`
(app/bandcamp/mapper.py) rely on it as their concurrent-worker race backstop --
two crawl workers ingesting overlapping collection pages for the same fan is
the common case, not the exotic one -- so the race silently produced duplicate
rows, inflating the owned/wishlist counts `GET /api/stats` and
`neighbour_size_report` compute.

Two partial unique indexes (one per item type) close the gap for real:
uq_fan_item_album on (fan_id, album_id) WHERE track_id IS NULL, and
uq_fan_item_track on (fan_id, track_id) WHERE album_id IS NULL. `item_type`
itself is redundant once split this way -- album_id is only ever set on an
album row and track_id only ever on a track row.

No data cleanup needed: existing duplicates (if any slipped through) simply
stay as separate rows; this only stops new ones. See
team/memory/backlog.md.

Guarded like 0002-0017: a fresh DB builds this from the current ORM metadata,
so this only patches an EXISTING DB.

Revision ID: 0018_fan_item_partial_unique
Revises: 0017_frontier_timeout_count
Create Date: 2026-09-08

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_fan_item_partial_unique"
down_revision: str | None = "0017_frontier_timeout_count"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "fan_items"
_OLD_UNIQUE = ["fan_id", "item_type", "album_id", "track_id"]
_ALBUM_INDEX = "uq_fan_item_album"
_TRACK_INDEX = "uq_fan_item_track"


def _find_unique(table: str, columns: list[str]) -> tuple[str, str] | None:
    """(name, 'constraint'|'index') of a unique covering exactly these columns.
    Checks both, since a column-level unique can materialize as either."""
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return None
    for uc in insp.get_unique_constraints(table):
        if uc.get("column_names") == columns:
            return uc["name"], "constraint"
    for ix in insp.get_indexes(table):
        if ix.get("unique") and ix.get("column_names") == columns:
            return ix["name"], "index"
    return None


def _has_index(table: str, name: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return False
    return any(ix["name"] == name for ix in insp.get_indexes(table))


def upgrade() -> None:
    if _has_index(_TABLE, _ALBUM_INDEX):
        return  # fresh DB built from ORM metadata, or already migrated

    found = _find_unique(_TABLE, _OLD_UNIQUE)
    if found is not None:
        name, kind = found
        with op.batch_alter_table(_TABLE) as batch:
            if kind == "constraint":
                batch.drop_constraint(name, type_="unique")
            else:
                batch.drop_index(name)

    op.create_index(
        _ALBUM_INDEX, _TABLE, ["fan_id", "album_id"], unique=True,
        sqlite_where=sa.text("track_id IS NULL"),
        postgresql_where=sa.text("track_id IS NULL"),
    )
    op.create_index(
        _TRACK_INDEX, _TABLE, ["fan_id", "track_id"], unique=True,
        sqlite_where=sa.text("album_id IS NULL"),
        postgresql_where=sa.text("album_id IS NULL"),
    )


def downgrade() -> None:
    if not _has_index(_TABLE, _ALBUM_INDEX):
        return
    op.drop_index(_ALBUM_INDEX, table_name=_TABLE)
    op.drop_index(_TRACK_INDEX, table_name=_TABLE)
    with op.batch_alter_table(_TABLE) as batch:
        batch.create_unique_constraint("uq_fan_item", _OLD_UNIQUE)
