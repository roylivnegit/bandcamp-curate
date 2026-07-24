"""Response cache so re-runs don't re-spend Nimble credits.

`NullCache` is the default (no caching). `RedisCache` stores the parsed payload
keyed by parser+URL with a short TTL. Longer-term storage of raw payloads lives in
the `raw_pages` table and is written by the crawl layer (M3).
"""

import json
from typing import Any, Protocol

from app.scraping.base import FetchRequest, FetchResult


class ResponseCache(Protocol):
    async def get(self, request: FetchRequest) -> FetchResult | None: ...
    async def set(self, request: FetchRequest, result: FetchResult) -> None: ...


class NullCache:
    async def get(self, request: FetchRequest) -> FetchResult | None:
        return None

    async def set(self, request: FetchRequest, result: FetchResult) -> None:
        return None


def _serialize(result: FetchResult) -> str:
    return json.dumps(
        {
            "url": result.url,
            "provider": result.provider,
            "status_code": result.status_code,
            "ok": result.ok,
            "parsing_status": result.parsing_status,
            "entities": result.entities,
            "html": result.html,
            "quota_remaining": result.quota_remaining,
        }
    )


def _deserialize(payload: str) -> FetchResult:
    data: dict[str, Any] = json.loads(payload)
    return FetchResult(
        url=data["url"],
        provider=data["provider"],
        status_code=data["status_code"],
        ok=data["ok"],
        parsing_status=data.get("parsing_status"),
        entities=data.get("entities"),
        html=data.get("html"),
        quota_remaining=data.get("quota_remaining"),
        from_cache=True,
    )


class RedisCache:
    """Redis-backed cache. `client` is an async redis client (redis.asyncio)."""

    def __init__(self, client: Any, ttl_seconds: int = 3600, namespace: str = "scrape") -> None:
        self._client = client
        self._ttl = ttl_seconds
        self._ns = namespace

    def _key(self, request: FetchRequest) -> str:
        return f"{self._ns}:{request.cache_key()}"

    async def get(self, request: FetchRequest) -> FetchResult | None:
        payload = await self._client.get(self._key(request))
        if payload is None:
            return None
        if isinstance(payload, bytes):
            payload = payload.decode()
        return _deserialize(payload)

    async def set(self, request: FetchRequest, result: FetchResult) -> None:
        if not result.parsed_ok:
            return  # only cache successful parses
        await self._client.set(self._key(request), _serialize(result), ex=self._ttl)
