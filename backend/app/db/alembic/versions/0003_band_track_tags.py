"""add band_tags + track_tags, backfilled from album_tags

Guarded like 0002: a fresh DB gets these tables from the 0001 metadata baseline, so
this migration only patches an existing DB. It also backfills the two new tables
from the album tags already ingested (a band gets its albums' tags; a track gets
its album's tags).

Revision ID: 0003_band_track_tags
Revises: 0002_fan_item_wishlist
Create Date: 2026-07-24

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_band_track_tags"
down_revision: str | None = "0002_fan_item_wishlist"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _has_table("band_tags"):
        op.create_table(
            "band_tags",
            sa.Column("band_id", sa.Integer(), sa.ForeignKey("bands.id"), primary_key=True),
            sa.Column("tag_id", sa.Integer(), sa.ForeignKey("tags.id"), primary_key=True),
        )
    if not _has_table("track_tags"):
        op.create_table(
            "track_tags",
            sa.Column("track_id", sa.Integer(), sa.ForeignKey("tracks.id"), primary_key=True),
            sa.Column("tag_id", sa.Integer(), sa.ForeignKey("tags.id"), primary_key=True),
        )
    # Backfill from existing album_tags (idempotent — INSERT ... WHERE NOT EXISTS).
    op.execute(
        """
        INSERT INTO band_tags (band_id, tag_id)
        SELECT DISTINCT a.band_id, at.tag_id
        FROM album_tags at JOIN albums a ON a.id = at.album_id
        WHERE a.band_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM band_tags bt
                          WHERE bt.band_id = a.band_id AND bt.tag_id = at.tag_id)
        """
    )
    op.execute(
        """
        INSERT INTO track_tags (track_id, tag_id)
        SELECT DISTINCT t.id, at.tag_id
        FROM album_tags at JOIN tracks t ON t.album_id = at.album_id
        WHERE NOT EXISTS (SELECT 1 FROM track_tags tt
                          WHERE tt.track_id = t.id AND tt.tag_id = at.tag_id)
        """
    )


def downgrade() -> None:
    for name in ("band_tags", "track_tags"):
        if _has_table(name):
            op.drop_table(name)
