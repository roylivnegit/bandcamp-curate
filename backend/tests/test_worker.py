import pytest

from app.config import Settings
from app.worker import seed_crawl
from scripts.crawl import cmd_run, cmd_seed


async def test_seed_crawl_disabled_by_default():
    """The legacy operator crawl chain refuses unless explicitly opted into."""
    settings = Settings(enable_operator_crawl=False)
    ctx = {"settings": settings}
    with pytest.raises(RuntimeError, match="disabled"):
        await seed_crawl(ctx)


async def test_seed_crawl_disabled_does_not_touch_sessionmaker_or_redis():
    """The guard must fire before anything else runs, so ctx need not carry a
    real sessionmaker/redis connection for the disabled case."""
    settings = Settings(enable_operator_crawl=False)
    ctx: dict = {"settings": settings}  # no "sessionmaker" or "redis" key at all
    with pytest.raises(RuntimeError):
        await seed_crawl(ctx)


async def test_cmd_seed_refuses_when_operator_crawl_disabled(monkeypatch):
    import scripts.crawl as crawl_script

    monkeypatch.setattr(
        crawl_script, "get_settings", lambda: Settings(enable_operator_crawl=False)
    )
    assert await cmd_seed() == 2


async def test_cmd_run_refuses_when_operator_crawl_disabled(monkeypatch):
    import scripts.crawl as crawl_script

    monkeypatch.setattr(
        crawl_script, "get_settings", lambda: Settings(enable_operator_crawl=False)
    )
    assert await cmd_run(5) == 2
