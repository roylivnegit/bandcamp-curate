"""add blacklist.expires_at (temporary "not now" blocks)

`POST /api/blacklist` had no expiry — blocking a band was permanent or a manual
unblock forever. Someone annoyed by an artist's recs today had no way to say
"not now" without either living with them or losing the block entirely.
See team/memory/backlog.md "Blacklist is all-or-nothing forever".

Nullable: NULL keeps today's behavior (blocked indefinitely). A non-null value
is a "not now" — `build_exclusions` filters to rows where `expires_at IS NULL
OR expires_at > now()`, so a row past its expiry silently stops excluding
without anyone needing to unblock it by hand.

Guarded like 0002-0011: a fresh DB builds this from the current ORM metadata,
so this only patches an EXISTING DB.

Revision ID: 0012_blacklist_expires_at
Revises: 0011_provider_usage_scan_id
Create Date: 2026-09-02

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_blacklist_expires_at"
down_revision: str | None = "0011_provider_usage_scan_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "blacklist"
_COLUMN = "expires_at"


def _has_column(table: str, col: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return False
    return any(c["name"] == col for c in insp.get_columns(table))


def upgrade() -> None:
    if _has_column(_TABLE, _COLUMN):
        return  # fresh DB built from ORM metadata, or already migrated
    with op.batch_alter_table(_TABLE) as batch:
        batch.add_column(sa.Column(_COLUMN, sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    if not _has_column(_TABLE, _COLUMN):
        return
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_column(_COLUMN)
