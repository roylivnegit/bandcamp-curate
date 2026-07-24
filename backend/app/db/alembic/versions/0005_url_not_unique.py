"""drop UNIQUE on bands/albums/tracks .url

Bandcamp URLs are not globally unique across items (single-track albums, remasters,
VA compilations reuse a URL; a "track" collection item can even carry an /album/
URL). The unique index blew up mid-crawl on duplicate-key violations and lost whole
fans. `bandcamp_id` is the natural key; `url` stays indexed but non-unique.

Guarded (see 0002–0004): a fresh DB already builds `url` non-unique from the current
metadata baseline, so this only patches an existing DB. Idempotent — skips any
column whose url index is already non-unique.

Revision ID: 0005_url_not_unique
Revises: 0004_likes
Create Date: 2026-07-24

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_url_not_unique"
down_revision: str | None = "0004_likes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("bands", "albums", "tracks")


def _url_index(table: str) -> dict | None:
    insp = sa.inspect(op.get_bind())
    for ix in insp.get_indexes(table):
        if ix.get("column_names") == ["url"]:
            return ix
    return None


def upgrade() -> None:
    for table in _TABLES:
        ix = _url_index(table)
        if ix is not None and ix.get("unique"):
            op.drop_index(ix["name"], table_name=table)
        if _url_index(table) is None:
            op.create_index(f"ix_{table}_url", table, ["url"], unique=False)


def downgrade() -> None:
    # No-op: re-adding UNIQUE would fail on the very data this migration allows.
    pass
