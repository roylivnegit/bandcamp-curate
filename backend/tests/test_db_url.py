from app.db.url import normalized_async_url


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
