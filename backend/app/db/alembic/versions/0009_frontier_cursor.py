"""add crawl_frontier.cursor (resumable pagination bookmark)

A fan collection can hold thousands of items (p90 in our data is ~1,700 ≈ 43
pages). Paging one to the end inside a single job took longer than ARQ's
`job_timeout`, and because the old loop accumulated every page in memory and
committed once at the very end, a timeout threw away the whole collection —
along with the Nimble credits spent discovering it.

Pagination is now bounded per visit and committed per page. This column stores
the next-page tokens so the following visit resumes where the last one stopped
instead of starting over: `{"collection": tok|None, "wishlist": tok|None,
"follows": tok|None}`, NULL meaning nothing in flight (never visited, or fully
paged). An entry with a cursor stays PENDING, and `claim_next` orders by
`attempts` so every other entry gets a turn before it comes round again.

Guarded like 0002-0008: a fresh DB builds this straight from the current ORM
metadata, so this only patches an EXISTING DB. Purely additive and nullable —
existing rows get NULL, which reads as "not started", exactly right for entries
enqueued before this change.

Revision ID: 0009_frontier_cursor
Revises: 0008_users_and_ownership
Create Date: 2026-08-06

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0009_frontier_cursor"
down_revision: str | None = "0008_users_and_ownership"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "crawl_frontier"
_COLUMN = "cursor"


def _has_column(table: str, col: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return False
    return any(c["name"] == col for c in insp.get_columns(table))


def _json_type() -> sa.types.TypeEngine:
    """JSONB on Postgres, plain JSON elsewhere — mirrors models.JSONVariant so
    SQLite test databases migrate too."""
    return sa.JSON().with_variant(JSONB, "postgresql")


def upgrade() -> None:
    if _has_column(_TABLE, _COLUMN):
        return  # fresh DB built from ORM metadata, or already migrated
    op.add_column(_TABLE, sa.Column(_COLUMN, _json_type(), nullable=True))


def downgrade() -> None:
    if not _has_column(_TABLE, _COLUMN):
        return
    op.drop_column(_TABLE, _COLUMN)
