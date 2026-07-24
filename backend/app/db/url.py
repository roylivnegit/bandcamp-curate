"""Normalize a DATABASE_URL for SQLAlchemy's asyncpg driver.

Managed Postgres providers (Neon, Supabase, Railway, …) hand you a libpq-style
URL like ``postgresql://u:p@host/db?sslmode=require&channel_binding=require`` —
no ``+asyncpg`` driver suffix, and query params asyncpg doesn't understand.
This turns such a URL into ``(async_url, connect_args)`` that create_async_engine
accepts, while leaving already-correct URLs (and non-Postgres URLs like the
SQLite test DB) untouched.
"""

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# libpq params asyncpg rejects; we translate/drop them rather than pass them on.
_SSL_ENABLING = {"require", "verify-ca", "verify-full", "prefer", "allow"}
_DROP_PARAMS = {"sslmode", "channel_binding"}


def normalized_async_url(url: str) -> tuple[str, dict[str, Any]]:
    """Return ``(url, connect_args)`` safe for create_async_engine.

    - Forces the async driver for bare ``postgres(ql)://`` URLs.
    - Translates ``sslmode`` into asyncpg's ``ssl`` connect arg and strips the
      libpq-only query params asyncpg would choke on.
    - No-ops for non-Postgres URLs (e.g. sqlite+aiosqlite).
    """
    parts = urlsplit(url)
    scheme = parts.scheme

    # Only Postgres needs massaging; leave sqlite/etc. exactly as given.
    if not scheme.startswith("postgres"):
        return url, {}

    if "+" not in scheme:  # bare postgres:// or postgresql:// → async driver
        scheme = "postgresql+asyncpg"

    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    connect_args: dict[str, Any] = {}

    sslmode = params.get("sslmode")
    if sslmode in _SSL_ENABLING:
        connect_args["ssl"] = True
    elif sslmode == "disable":
        connect_args["ssl"] = False

    for key in _DROP_PARAMS:
        params.pop(key, None)

    new_url = urlunsplit(
        (scheme, parts.netloc, parts.path, urlencode(params), parts.fragment)
    )
    return new_url, connect_args
