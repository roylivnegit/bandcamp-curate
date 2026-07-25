"""add scans + scan_seeds; recommendations.scan_id (per-scan feed)

M7 Stage 1. Introduces named scans: recommendations become per-scan while the
Bandcamp graph, the exclusion base (collection/wishlist/follows), blocked and
liked stay shared.

Guarded like 0002-0005: a fresh DB builds scans/scan_seeds and recommendations
.scan_id straight from the 0001 metadata baseline, so this only patches an
EXISTING DB. On an existing DB it also creates the "My collection" scan and
backfills every current recommendation onto it, then makes scan_id NOT NULL and
swaps the unique constraint to include scan_id. (A fresh DB gets its "My
collection" scan lazily at curate() time via ensure_collection_scan.)

Revision ID: 0006_scans
Revises: 0005_url_not_unique
Create Date: 2026-07-25

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.models import JSONVariant  # JSONB on Postgres, JSON elsewhere

revision: str = "0006_scans"
down_revision: str | None = "0005_url_not_unique"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _has_column(table: str, col: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return any(c["name"] == col for c in insp.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()

    if not _has_table("scans"):
        op.create_table(
            "scans",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("kind", sa.String(length=16), nullable=False, server_default="custom"),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
            sa.Column("error", sa.Text()),
            sa.Column("stats", JSONVariant),
            sa.Column("last_run_at", sa.DateTime(timezone=True)),
            sa.Column(
                "created_at", sa.DateTime(timezone=True),
                server_default=sa.func.now(), nullable=False,
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True),
                server_default=sa.func.now(), nullable=False,
            ),
        )
        op.create_index("ix_scans_kind", "scans", ["kind"])
        op.create_index("ix_scans_status", "scans", ["status"])

    if not _has_table("scan_seeds"):
        op.create_table(
            "scan_seeds",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "scan_id", sa.Integer(),
                sa.ForeignKey("scans.id", ondelete="CASCADE"),
                nullable=False, index=True,
            ),
            sa.Column("url", sa.String(length=512), nullable=False),
            sa.Column("seed_type", sa.String(length=16), nullable=False),
            sa.Column("resolved_album_id", sa.Integer(), sa.ForeignKey("albums.id"), index=True),
            sa.Column("resolved_track_id", sa.Integer(), sa.ForeignKey("tracks.id"), index=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if not _has_column("recommendations", "scan_id"):
        # 1. add nullable, so existing rows survive the ALTER
        op.add_column("recommendations", sa.Column("scan_id", sa.Integer()))
        # 2. ensure the "My collection" scan exists, get its id
        scan_id = bind.execute(
            sa.text("SELECT id FROM scans WHERE kind = 'collection' ORDER BY id LIMIT 1")
        ).scalar()
        if scan_id is None:
            scan_id = bind.execute(
                sa.text(
                    "INSERT INTO scans (name, kind, status, created_at, updated_at) "
                    "VALUES ('My collection', 'collection', 'done', now(), now()) RETURNING id"
                )
            ).scalar()
        # 3. backfill every existing recommendation onto it
        bind.execute(
            sa.text("UPDATE recommendations SET scan_id = :sid WHERE scan_id IS NULL"),
            {"sid": scan_id},
        )
        # 4. lock it down + reindex + swap the unique constraint to include scan_id
        op.alter_column("recommendations", "scan_id", nullable=False)
        op.create_foreign_key(
            "fk_recommendations_scan_id", "recommendations", "scans",
            ["scan_id"], ["id"], ondelete="CASCADE",
        )
        op.create_index("ix_recommendations_scan_id", "recommendations", ["scan_id"])
        op.drop_constraint("uq_recommendation_item", "recommendations", type_="unique")
        op.create_unique_constraint(
            "uq_recommendation_item", "recommendations",
            ["scan_id", "item_type", "album_id", "track_id"],
        )


def downgrade() -> None:
    # No-op: the per-scan feed is not designed to roll back cleanly (recs would
    # lose their scan and the unique constraint would collide).
    pass
