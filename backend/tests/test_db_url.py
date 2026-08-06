from app.db.url import is_pooled_endpoint, normalized_async_url


def test_neon_style_url_gets_driver_and_ssl() -> None:
    url, ca = normalized_async_url(
        "postgresql://u:p@ep-x.aws.neon.tech/db?sslmode=require&channel_binding=require"
    )
    assert url == "postgresql+asyncpg://u:p@ep-x.aws.neon.tech/db"
    assert ca == {"ssl": True}


def test_local_asyncpg_url_untouched() -> None:
    src = "postgresql+asyncpg://crate:crate@localhost:5432/crate"
    url, ca = normalized_async_url(src)
    assert url == src and ca == {}


def test_sslmode_disable_maps_to_ssl_false() -> None:
    url, ca = normalized_async_url("postgresql://u:p@host/db?sslmode=disable")
    assert ca == {"ssl": False} and "sslmode" not in url


def test_sqlite_url_is_a_noop() -> None:
    src = "sqlite+aiosqlite://"
    assert normalized_async_url(src) == (src, {})


def test_pooled_endpoint_disables_prepared_statement_caches() -> None:
    """A transaction pooler hands each transaction a different backend, so a
    statement prepared on one isn't there on the next — the reason this project
    stuck to the direct endpoint. Both caches must be off for the pooler to work."""
    url = (
        "postgresql://u:p@ep-x-pooler.c-4.eu-central-1.aws.neon.tech/db"
        "?sslmode=require&channel_binding=require"
    )
    new_url, connect_args = normalized_async_url(url)
    assert is_pooled_endpoint(url) is True
    assert connect_args["statement_cache_size"] == 0  # asyncpg's own cache
    assert "prepared_statement_cache_size=0" in new_url  # SQLAlchemy's
    assert connect_args["ssl"] is True  # still translated as usual


def test_direct_endpoint_keeps_prepared_statements() -> None:
    # Caching is a real speedup; only the pooler can't have it.
    url = "postgresql://u:p@ep-x.eu-central-1.aws.neon.tech/db?sslmode=require"
    new_url, connect_args = normalized_async_url(url)
    assert is_pooled_endpoint(url) is False
    assert "statement_cache_size" not in connect_args
    assert "prepared_statement_cache_size" not in new_url
