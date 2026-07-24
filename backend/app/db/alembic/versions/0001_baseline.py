"""baseline schema

Creates the full M0 schema directly from the ORM metadata so the migration can
never drift from the models. Subsequent migrations use normal autogenerate.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-07-24

"""
from collections.abc import Sequence

from alembic import op

from app.db.base import Base

# Import models so every table registers on Base.metadata before create_all.
from app.db import models  # noqa: F401

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
