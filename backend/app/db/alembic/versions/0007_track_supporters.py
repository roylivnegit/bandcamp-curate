"""add track_supporters (M7 track-seed support)

Track scan seeds need their own supporter edges — a fan supports a specific
track independently of its album — so co-ownership among a track-seeded scan's
taste-neighbours has somewhere to land. Mirrors album_supporters exactly.

Guarded like 0002-0006: a fresh DB gets this table straight from the 0001
metadata baseline, so this only patches an EXISTING DB.

Revision ID: 0007_track_supporters
Revises: 0006_scans
Create Date: 2026-07-25

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_track_supporters"
down_revision: str | None = "0006_scans"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _has_table("track_supporters"):
        op.create_table(
            "track_supporters",
            sa.Column("track_id", sa.Integer(), sa.ForeignKey("tracks.id"), primary_key=True),
            sa.Column("fan_id", sa.Integer(), sa.ForeignKey("fans.id"), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )


def downgrade() -> None:
    op.drop_table("track_supporters")
