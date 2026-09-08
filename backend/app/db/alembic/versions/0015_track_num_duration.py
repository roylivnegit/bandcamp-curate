"""add tracks.track_num and tracks.duration

`app/bandcamp/parse.py`'s `ParsedTrack` (an entry in an album page's
`trackinfo[]`) has always parsed `track_num` and `duration`, but nothing
downstream stored either — same "parsed and then silently dropped" shape as
`art_id` before 0014. See team/memory/backlog.md "Persist Track.track_num /
Track.duration".

Tracks only, not albums: these are per-track fields, an album has no single
duration/track_num. Also not populated by the standalone track-page path
(`ingest_track_page`) — `ParsedTrackPage` carries neither field; Bandcamp
doesn't expose a position/duration off-album.

Guarded like 0002-0014: a fresh DB builds this from the current ORM
metadata, so this only patches an EXISTING DB.

Revision ID: 0015_track_num_duration
Revises: 0014_art_id
Create Date: 2026-09-03

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_track_num_duration"
down_revision: str | None = "0014_art_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "tracks"
_COLUMNS = ("track_num", "duration")


def _has_column(table: str, col: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return False
    return any(c["name"] == col for c in insp.get_columns(table))


def upgrade() -> None:
    with op.batch_alter_table(_TABLE) as batch:
        if not _has_column(_TABLE, "track_num"):
            batch.add_column(sa.Column("track_num", sa.Integer(), nullable=True))
        if not _has_column(_TABLE, "duration"):
            batch.add_column(sa.Column("duration", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table(_TABLE) as batch:
        for col in _COLUMNS:
            if _has_column(_TABLE, col):
                batch.drop_column(col)
