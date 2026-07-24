"""Mimic Bandcamp's `collection_items` XHR to page through a fan's full collection.

When you scroll a fan page, the browser POSTs to a clean public JSON endpoint:

    POST https://bandcamp.com/api/fancollection/1/collection_items
    {"fan_id": <int>, "older_than_token": "<token>", "count": <int>}
    → {"items": [...], "more_available": bool, "last_token": "<token>", ...}

We call that endpoint directly rather than rendering the page and auto-scrolling —
it's cheaper, deterministic, and the `items[]` share the exact shape
`parse_collection_item()` already handles. The first `older_than_token` is the fan
page blob's `collection_data.last_token`; each response's `last_token` feeds the next
call until `more_available` is false.

The endpoint is public (no auth). This client hits Bandcamp directly; if that ever
gets IP-throttled at scale, swap the transport to route through the ScraperGateway
(Nimble) — the pagination logic here is transport-agnostic via the injected client.
"""

from collections.abc import AsyncIterator

import httpx

from app.bandcamp.parse import ParsedItem, parse_collection_items_api

COLLECTION_ITEMS_URL = "https://bandcamp.com/api/fancollection/1/collection_items"
DEFAULT_COUNT = 40
# A browser-like UA; the API is public but bare clients are sometimes rejected.
_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Content-Type": "application/json",
    "Accept": "application/json",
}


class CollectionApiClient:
    """Pages through the `collection_items` API. Injectable client for testing."""

    def __init__(
        self, client: httpx.AsyncClient | None = None, *, count: int = DEFAULT_COUNT
    ) -> None:
        self._client = client
        self._count = count

    async def fetch_page(
        self, fan_id: int, older_than_token: str, *, count: int | None = None
    ) -> tuple[list[ParsedItem], str | None, bool]:
        """Fetch one page → (items, last_token, more_available)."""
        payload = {
            "fan_id": fan_id,
            "older_than_token": older_than_token,
            "count": count or self._count,
        }
        client = self._client or httpx.AsyncClient(timeout=30.0, headers=_DEFAULT_HEADERS)
        owns_client = self._client is None
        try:
            resp = await client.post(COLLECTION_ITEMS_URL, json=payload)
            resp.raise_for_status()
            body = resp.json()
        finally:
            if owns_client:
                await client.aclose()
        return parse_collection_items_api(body)

    async def iter_items(
        self, fan_id: int, start_token: str, *, max_pages: int = 100
    ) -> AsyncIterator[ParsedItem]:
        """Yield every item after `start_token`, following pagination to the end."""
        token: str | None = start_token
        for _ in range(max_pages):
            if not token:
                return
            items, last_token, more = await self.fetch_page(fan_id, token)
            for item in items:
                yield item
            if not more or not last_token or last_token == token:
                return
            token = last_token
