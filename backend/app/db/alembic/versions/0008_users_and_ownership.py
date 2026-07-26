"""add users + ownership scoping (multi-tenant auth)

Introduces real app accounts (username/password login). Each `User` owns a set
of `scans`/`likes`/`blacklist` rows (new `user_id` FK on each) and is linked to
the Bandcamp `Fan` row that IS them via `users.fan_id` — the per-tenant
replacement for the old global `Fan.is_me` flag (kept as legacy bookkeeping,
no longer read for identity). The shared Bandcamp catalog/graph (bands, albums,
tracks, tags, fans, fan_items, supporters, crawl_frontier) stays global —
crawling one user's graph benefits everyone's future discovery.

Also fixes a latent cross-tenant leak: `follows` had no per-fan scoping at all
(globally unique on `band_id`) — one fan following a label would have
suppressed it from every other fan's feed. Adds `follows.fan_id` and rescopes
the uniqueness to `(fan_id, band_id)`.

Guarded like 0002-0007: a fresh DB builds all of this straight from the current
ORM metadata, so this only patches an EXISTING DB. On an existing DB it also
backfills one "operator" User from whatever single `is_me=True` Fan already
exists (the pre-multi-tenancy deployer), attaches every existing scan/like/
blacklist row to that user, and re-scopes `follows` to that same Fan. The
backfilled user gets an unusable placeholder password ("!" — bcrypt.checkpw
against it always raises/returns False) since a migration can't securely hash
a real one; use `scripts/set_password.py` right after migrating to set a real
password (and `PATCH`-equivalent update of `bandcamp_fan_url` isn't needed here
since that Fan is already crawled).

If a populated DB can't be backfilled (rows exist but no `is_me` fan does), this
ABORTS rather than leaving NULL owners behind — see `_lock_not_null`. An unowned
row would be permanently invisible to the app's ownership scoping, which is a
worse outcome than a failed migration the operator can fix and re-run.

Revision ID: 0008_users_and_ownership
Revises: 0007_track_supporters
Create Date: 2026-07-26

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_users_and_ownership"
down_revision: str | None = "0007_track_supporters"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OWNED_TABLES = ("scans", "likes", "blacklist")


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _has_column(table: str, col: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return any(c["name"] == col for c in insp.get_columns(table))


def _find_unique(table: str, columns: list[str]) -> tuple[str, str] | None:
    """(name, 'constraint'|'index') of a unique constraint/index covering
    exactly these columns, or None. Checks both since a column-level
    `unique=True` can materialize as either depending on dialect/version."""
    insp = sa.inspect(op.get_bind())
    for uc in insp.get_unique_constraints(table):
        if uc.get("column_names") == columns:
            return uc["name"], "constraint"
    for ix in insp.get_indexes(table):
        if ix.get("unique") and ix.get("column_names") == columns:
            return ix["name"], "index"
    return None


def _drop_unique(table: str, columns: list[str]) -> None:
    found = _find_unique(table, columns)
    if found is None:
        return
    name, kind = found
    if kind == "constraint":
        op.drop_constraint(name, table, type_="unique")
    else:
        op.drop_index(name, table_name=table)


def _lock_not_null(table: str, col: str, *, fix: str) -> None:
    """Make `table.col` NOT NULL, refusing to continue if any row is still NULL.

    Leaving NULLs behind would be worse than failing: the app scopes everything by
    these columns, so an unowned row becomes permanently invisible — no user can
    see it, and nothing surfaces that it exists. An empty table locks down fine;
    only a populated-but-unbackfillable one aborts, with `fix` telling the
    operator how to unblock."""
    remaining = op.get_bind().execute(
        sa.text(f"SELECT count(*) FROM {table} WHERE {col} IS NULL")  # noqa: S608
    ).scalar()
    if remaining:
        raise RuntimeError(
            f"migration 0008 cannot continue: {remaining} row(s) in `{table}` have a "
            f"NULL `{col}` and could not be backfilled. {fix}"
        )
    op.alter_column(table, col, nullable=False)


def upgrade() -> None:
    bind = op.get_bind()

    if not _has_table("users"):
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("username", sa.String(length=256), nullable=False),
            sa.Column("password_hash", sa.String(length=256), nullable=False),
            sa.Column("fan_id", sa.Integer(), sa.ForeignKey("fans.id")),
            sa.Column("bandcamp_fan_url", sa.String(length=512)),
            sa.Column(
                "created_at", sa.DateTime(timezone=True),
                server_default=sa.func.now(), nullable=False,
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True),
                server_default=sa.func.now(), nullable=False,
            ),
        )
        op.create_index("ix_users_username", "users", ["username"], unique=True)
        op.create_index("ix_users_fan_id", "users", ["fan_id"], unique=True)

    # ── follows: scope per-fan (fixes the cross-tenant leak) ──────────────────
    if not _has_column("follows", "fan_id"):
        op.add_column("follows", sa.Column("fan_id", sa.Integer()))
        me_id = bind.execute(
            sa.text("SELECT id FROM fans WHERE is_me = true ORDER BY id LIMIT 1")
        ).scalar()
        if me_id is not None:
            bind.execute(
                sa.text("UPDATE follows SET fan_id = :me WHERE fan_id IS NULL"), {"me": me_id}
            )
        _lock_not_null(
            "follows", "fan_id",
            fix="No `fans` row is flagged is_me, so there's no fan to attribute existing "
                "follows to. Flag the right fan (UPDATE fans SET is_me = true WHERE ...) "
                "and re-run, or delete the orphaned follows if they're stale.",
        )
        op.create_foreign_key("fk_follows_fan_id", "follows", "fans", ["fan_id"], ["id"])
        op.create_index("ix_follows_fan_id", "follows", ["fan_id"])
        _drop_unique("follows", ["band_id"])
        if _find_unique("follows", ["fan_id", "band_id"]) is None:
            op.create_unique_constraint("uq_follow_fan_band", "follows", ["fan_id", "band_id"])

    # ── backfill one "operator" user from the pre-existing is_me fan ──────────
    operator_user_id = bind.execute(sa.text("SELECT id FROM users LIMIT 1")).scalar()
    if operator_user_id is None:
        me_row = bind.execute(
            sa.text("SELECT id, username FROM fans WHERE is_me = true ORDER BY id LIMIT 1")
        ).first()
        if me_row is not None:
            operator_user_id = bind.execute(
                sa.text(
                    "INSERT INTO users (username, password_hash, fan_id, created_at, updated_at) "
                    "VALUES (:username, '!', :fan_id, now(), now()) RETURNING id"
                ),
                {"username": me_row.username, "fan_id": me_row.id},
            ).scalar()

    # ── scans / likes / blacklist: add + backfill + lock down user_id ─────────
    for table in _OWNED_TABLES:
        if _has_column(table, "user_id"):
            continue
        op.add_column(table, sa.Column("user_id", sa.Integer()))
        if operator_user_id is not None:
            bind.execute(
                sa.text(f"UPDATE {table} SET user_id = :uid WHERE user_id IS NULL"),  # noqa: S608
                {"uid": operator_user_id},
            )
        _lock_not_null(
            table, "user_id",
            fix="No operator user could be created (no `fans` row is flagged is_me, and "
                "`users` was empty), so there's nobody to attribute these rows to. Flag "
                "the right fan (UPDATE fans SET is_me = true WHERE ...) and re-run, or "
                f"clear the stale `{table}` rows.",
        )
        op.create_foreign_key(f"fk_{table}_user_id", table, "users", ["user_id"], ["id"])
        op.create_index(f"ix_{table}_user_id", table, ["user_id"])

    # likes' item-uniqueness must include user_id (two users can each like the
    # same album independently) — swap the constraint now that the column exists.
    _drop_unique("likes", ["item_type", "album_id", "track_id"])
    if _find_unique("likes", ["user_id", "item_type", "album_id", "track_id"]) is None:
        op.create_unique_constraint(
            "uq_like_item", "likes", ["user_id", "item_type", "album_id", "track_id"]
        )


def downgrade() -> None:
    # No-op: matches 0005-0007's precedent — not designed to roll back cleanly.
    pass
