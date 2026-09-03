"""add albums.art_id and tracks.art_id

Bandcamp's page JSON already carries an `art_id` for both an album's tralbum
(`data-tralbum.current.art_id`) and a fan-collection item (`item_art_id`) —
`app/bandcamp/parse.py` has parsed it for a while, but nothing downstream
stored it, so it was parsed and then silently dropped. See
team/memory/backlog.md "Persist art_id onto albums/tracks".

Deliberately backend-only: no `art_url` construction or frontend rendering
here — just the column, threaded through ingestion, and exposed on
`GET /api/recommendations`. Building an actual image URL from the id is a
one-line format string for a future frontend-facing follow-up.

Guarded like 0002-0013: a fresh DB builds this from the current ORM
metadata, so this only patches an EXISTING DB.

Revision ID: 0014_art_id
Revises: 0013_scan_recompute_generation
Create Date: 2026-09-03

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_art_id"
down_revision: str | None = "0013_scan_recompute_generation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMN = "art_id"


def _has_column(table: str, col: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return False
    return any(c["name"] == col for c in insp.get_columns(table))


def upgrade() -> None:
    for table in ("albums", "tracks"):
        if _has_column(table, _COLUMN):
            continue  # fresh DB built from ORM metadata, or already migrated
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column(_COLUMN, sa.BigInteger(), nullable=True))


def downgrade() -> None:
    for table in ("albums", "tracks"):
        if not _has_column(table, _COLUMN):
            continue
        with op.batch_alter_table(table) as batch:
            batch.drop_column(_COLUMN)
