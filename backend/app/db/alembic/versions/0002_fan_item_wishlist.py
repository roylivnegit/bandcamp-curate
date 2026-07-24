"""add fan_items.is_wishlist

The 0001 baseline builds from ORM metadata (`create_all`), so a *fresh* database
already gets `is_wishlist` from the current models. This migration only needs to
patch an *existing* database created before the column existed — so it is guarded
by an inspector check and is a no-op when the column is already present.

Revision ID: 0002_fan_item_wishlist
Revises: 0001_baseline
Create Date: 2026-07-24

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_fan_item_wishlist"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if _has_column("fan_items", "is_wishlist"):
        return
    op.add_column(
        "fan_items",
        sa.Column(
            "is_wishlist", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.create_index("ix_fan_items_is_wishlist", "fan_items", ["is_wishlist"])


def downgrade() -> None:
    if not _has_column("fan_items", "is_wishlist"):
        return
    op.drop_index("ix_fan_items_is_wishlist", table_name="fan_items")
    op.drop_column("fan_items", "is_wishlist")
