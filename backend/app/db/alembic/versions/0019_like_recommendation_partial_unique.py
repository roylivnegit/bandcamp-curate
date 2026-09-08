"""likes/recommendations: replace the no-op uq_like_item/uq_recommendation_item
with partial unique indexes

Same NULL-pattern bug `0018_fan_item_partial_unique` fixed for `fan_items`:
`uq_like_item` (on `(user_id, item_type, album_id, track_id)`) and
`uq_recommendation_item` (on `(scan_id, item_type, album_id, track_id)`) each
had one of `album_id`/`track_id` always NULL depending on `item_type`, and
standard SQL treats NULL as distinct from NULL even inside a unique
constraint -- so neither constraint ever actually rejected a duplicate row.
See team/memory/tried-and-failed.md's 2026-09-08 entry and
`0018_fan_item_partial_unique` for the full writeup; left unfixed there on
purpose (lower real-world exposure than `fan_items`: `Recommendation` rows are
wholesale cleared and reinserted by a single-writer `curate()` transaction,
and `Like` rows come from single user clicks, not a fan-out crawl -- but the
schema bug is identical, so the same fix applies).

Four partial unique indexes (one per item type per table) close the gap:
uq_like_item_album on (user_id, album_id) WHERE track_id IS NULL,
uq_like_item_track on (user_id, track_id) WHERE album_id IS NULL,
uq_recommendation_item_album on (scan_id, album_id) WHERE track_id IS NULL,
uq_recommendation_item_track on (scan_id, track_id) WHERE album_id IS NULL.
`item_type` itself is redundant once split this way.

No data cleanup needed: existing duplicates (if any slipped through) simply
stay as separate rows; this only stops new ones.

Guarded like 0002-0018: a fresh DB builds this from the current ORM metadata,
so this only patches an EXISTING DB.

Revision ID: 0019_like_recommendation_partial_unique
Revises: 0018_fan_item_partial_unique
Create Date: 2026-09-08

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_like_recommendation_partial_unique"
down_revision: str | None = "0018_fan_item_partial_unique"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = [
    # (table, old_unique_columns, id_column, album_index, track_index)
    ("likes", ["user_id", "item_type", "album_id", "track_id"], "user_id",
     "uq_like_item_album", "uq_like_item_track"),
    ("recommendations", ["scan_id", "item_type", "album_id", "track_id"], "scan_id",
     "uq_recommendation_item_album", "uq_recommendation_item_track"),
]


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
    for table, old_unique, id_col, album_index, track_index in _TABLES:
        if _has_index(table, album_index):
            continue  # fresh DB built from ORM metadata, or already migrated

        found = _find_unique(table, old_unique)
        if found is not None:
            name, kind = found
            with op.batch_alter_table(table) as batch:
                if kind == "constraint":
                    batch.drop_constraint(name, type_="unique")
                else:
                    batch.drop_index(name)

        op.create_index(
            album_index, table, [id_col, "album_id"], unique=True,
            sqlite_where=sa.text("track_id IS NULL"),
            postgresql_where=sa.text("track_id IS NULL"),
        )
        op.create_index(
            track_index, table, [id_col, "track_id"], unique=True,
            sqlite_where=sa.text("album_id IS NULL"),
            postgresql_where=sa.text("album_id IS NULL"),
        )


def downgrade() -> None:
    old_names = {"likes": "uq_like_item", "recommendations": "uq_recommendation_item"}
    for table, old_unique, _id_col, album_index, track_index in _TABLES:
        if not _has_index(table, album_index):
            continue
        op.drop_index(album_index, table_name=table)
        op.drop_index(track_index, table_name=table)
        with op.batch_alter_table(table) as batch:
            batch.create_unique_constraint(old_names[table], old_unique)
