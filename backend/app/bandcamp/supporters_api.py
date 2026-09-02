"""Mimic Bandcamp's collectors "thumbs" XHR to page through an album's supporters.

The album page embeds the first page of supporters in `#collectors-data`
(`thumbs[]` + `more_thumbs_available` + a per-thumb `token`). To get the rest,
the browser POSTs the collectors thumbs endpoint:

    POST https://bandcamp.com/api/tralbumcollectors/2/thumbs
    {"tralbum_type": "a", "tralbum_id": <id>, "token": "<token>", "count": <n>}
    → {"thumbs": [...], "more_thumbs_available": bool}

We call it directly and page via the last thumb's token — the response shares the
shape of the embedded blob, so `parse_thumbs_api()` handles both.

NOTE: the response shape is confirmed (it matches the embedded blob we parse from
the page), but the endpoint URL/version and request-body field names are inferred
and not yet verified against a live call — flagged in CLAUDE.md. Keep the request
constants below in one place so a single live check can correct them.
"""

import asyncio
from collections.abc import AsyncIterator

import httpx

from app.bandcamp.nimble_transport import GatewayFetcher, post_json_via_nimble
from app.bandcamp.parse import ParsedSupporter, parse_thumbs_api

THUMBS_URL = "https://bandcamp.com/api/tralbumcollectors/2/thumbs"
DEFAULT_COUNT = 40
DEFAULT_DELAY = 0.4  # pause between pages — avoid Bandcamp 429s on bulk pagination
_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Content-Type": "application/json",
    "Accept": "application/json",
}


class SupportersApiClient:
    """Pages through the collectors `thumbs` API. Injectable client for testing."""

    def __init__(
        self, client: httpx.AsyncClient | None = None, *, count: int = DEFAULT_COUNT,
        delay: float = DEFAULT_DELAY, gateway: GatewayFetcher | None = None,
    ) -> None:
        self._client = client
        self._count = count
        self._gateway = gateway
        self._delay = 0.0 if gateway is not None else delay

    async def fetch_page(
        self,
        tralbum_id: int,
        token: str,
        *,
        tralbum_type: str = "a",
        count: int | None = None,
        scan_id: int | None = None,
    ) -> tuple[list[ParsedSupporter], str | None, bool]:
        """Fetch one page → (supporters, last_token, more_available)."""
        payload = {
            "tralbum_type": tralbum_type,
            "tralbum_id": tralbum_id,
            "token": token,
            "count": count or self._count,
        }
        if self._gateway is not None:
            body = await post_json_via_nimble(
                self._gateway, THUMBS_URL, payload, scan_id=scan_id
            )
        else:
            client = self._client or httpx.AsyncClient(timeout=30.0, headers=_DEFAULT_HEADERS)
            owns_client = self._client is None
            try:
                resp = await client.post(THUMBS_URL, json=payload)
                resp.raise_for_status()
                body = resp.json()
            finally:
                if owns_client:
                    await client.aclose()
        return parse_thumbs_api(body)

    async def iter_supporters(
        self,
        tralbum_id: int,
        start_token: str,
        *,
        tralbum_type: str = "a",
        max_pages: int = 100,
        scan_id: int | None = None,
    ) -> AsyncIterator[ParsedSupporter]:
        """Yield every supporter after `start_token`, following pagination to the end."""
        token: str | None = start_token
        for _ in range(max_pages):
            if not token:
                return
            supporters, last_token, more = await self.fetch_page(
                tralbum_id, token, tralbum_type=tralbum_type, scan_id=scan_id
            )
            for s in supporters:
                yield s
            if not more or not last_token or last_token == token:
                return
            token = last_token
            if self._delay:
                await asyncio.sleep(self._delay)
