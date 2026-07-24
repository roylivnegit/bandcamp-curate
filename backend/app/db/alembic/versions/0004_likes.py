"""add likes table

Guarded like 0002/0003: a fresh DB gets `likes` from the 0001 metadata baseline, so
this only patches an existing DB.

Revision ID: 0004_likes
Revises: 0003_band_track_tags
Create Date: 2026-07-24

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_likes"
down_revision: str | None = "0003_band_track_tags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if _has_table("likes"):
        return
    op.create_table(
        "likes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("item_type", sa.String(length=16), nullable=False),
        sa.Column("album_id", sa.Integer(), sa.ForeignKey("albums.id"), index=True),
        sa.Column("track_id", sa.Integer(), sa.ForeignKey("tracks.id"), index=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.UniqueConstraint("item_type", "album_id", "track_id", name="uq_like_item"),
    )


def downgrade() -> None:
    if _has_table("likes"):
        op.drop_table("likes")
