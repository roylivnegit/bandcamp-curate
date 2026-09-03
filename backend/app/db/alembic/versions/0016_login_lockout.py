"""add users.failed_login_attempts and users.locked_until

The login endpoint (`app/api/auth.py`) did a bare password check with zero
attempt tracking or rate limiting — the only rate limiter in the codebase
(`app/scraping/ratelimit.py`) is for the unrelated Bandcamp-scraping token
bucket, not auth, and this app is publicly reachable (Render). See
team/memory/backlog.md "Login has no lockout/rate-limit".

`locked_until` mirrors `Blacklist.expires_at`'s shape: a plain timestamp
compared against `now()` at read time, no sweeper job needed.

Guarded like 0002-0015: a fresh DB builds this from the current ORM
metadata, so this only patches an EXISTING DB.

Revision ID: 0016_login_lockout
Revises: 0015_track_num_duration
Create Date: 2026-09-03

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_login_lockout"
down_revision: str | None = "0015_track_num_duration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "users"


def _has_column(table: str, col: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return False
    return any(c["name"] == col for c in insp.get_columns(table))


def upgrade() -> None:
    with op.batch_alter_table(_TABLE) as batch:
        if not _has_column(_TABLE, "failed_login_attempts"):
            batch.add_column(
                sa.Column(
                    "failed_login_attempts", sa.Integer(), nullable=False, server_default="0"
                )
            )
        if not _has_column(_TABLE, "locked_until"):
            batch.add_column(sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table(_TABLE) as batch:
        for col in ("failed_login_attempts", "locked_until"):
            if _has_column(_TABLE, col):
                batch.drop_column(col)
