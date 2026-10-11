"""Checks on the migration chain itself, not on what any one migration does."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND = Path(__file__).resolve().parent.parent

# Alembic creates `alembic_version.version_num` as VARCHAR(32) and never widens
# it. A longer id raises StringDataRightTruncationError *after* the migration's
# own DDL has run, so the upgrade rolls back and the database stays put.
#
# `0019_like_recommendation_partial_unique` was 39 characters, and the suite
# runs on SQLite, which ignores VARCHAR limits — so nothing caught it.
MAX_VERSION_NUM = 32


def _revisions():
    """Every revision, read through Alembic itself.

    Not by globbing and regexing the files: `alembic revision` names them after
    a random hash and quotes the id however its template feels like, so a
    hand-rolled parser silently skips the migrations most likely to be wrong.
    """
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "app" / "db" / "alembic"))
    return list(ScriptDirectory.from_config(cfg).walk_revisions())


def test_revision_ids_fit_alembics_version_column() -> None:
    too_long = {
        s.revision: len(s.revision) for s in _revisions() if len(s.revision) > MAX_VERSION_NUM
    }
    assert not too_long, (
        f"revision ids over {MAX_VERSION_NUM} chars cannot be written to "
        f"alembic_version on Postgres, so the upgrade rolls back: {too_long}"
    )


def test_the_chain_has_exactly_one_head() -> None:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "app" / "db" / "alembic"))
    heads = ScriptDirectory.from_config(cfg).get_heads()
    assert len(heads) == 1, f"`alembic upgrade head` is ambiguous with {len(heads)} heads: {heads}"
