"""Mimic Bandcamp's `following_bands` XHR to page through everyone you follow.

The fan page embeds only the first ~45 followed bands, but a fan can follow
thousands (`following_bands_count`). Curation must exclude *all* of them, so we page
the rest via the same public endpoint the fan page scrolls:

    POST https://bandcamp.com/api/fancollection/1/following_bands
    {"fan_id": <int>, "older_than_token": "<token>", "count": <int>}
    → {"followeers": [{band_id, name, url_hints, token}], "more_available": bool,
       "last_token": "<token>"}

(`followeers` is Bandcamp's spelling.) Verified live 2026-07-24.
"""

import asyncio
from collections.abc import AsyncIterator

import httpx

from app.bandcamp.nimble_transport import GatewayFetcher, post_json_via_nimble
from app.bandcamp.parse import ParsedBand, parse_following_bands_api

FOLLOWING_BANDS_URL = "https://bandcamp.com/api/fancollection/1/following_bands"
DEFAULT_COUNT = 60
DEFAULT_DELAY = 0.4  # pause between pages — avoid Bandcamp 429s on bulk pagination
_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Content-Type": "application/json",
    "Accept": "application/json",
}


class FollowsApiClient:
    """Pages through the `following_bands` API. Injectable client for testing."""

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
        fan_id: int,
        older_than_token: str,
        *,
        count: int | None = None,
        scan_id: int | None = None,
    ) -> tuple[list[ParsedBand], str | None, bool]:
        payload = {
            "fan_id": fan_id,
            "older_than_token": older_than_token,
            "count": count or self._count,
        }
        if self._gateway is not None:
            body = await post_json_via_nimble(
                self._gateway, FOLLOWING_BANDS_URL, payload, scan_id=scan_id
            )
        else:
            client = self._client or httpx.AsyncClient(timeout=30.0, headers=_DEFAULT_HEADERS)
            owns_client = self._client is None
            try:
                resp = await client.post(FOLLOWING_BANDS_URL, json=payload)
                resp.raise_for_status()
                body = resp.json()
            finally:
                if owns_client:
                    await client.aclose()
        return parse_following_bands_api(body)

    async def iter_bands(
        self,
        fan_id: int,
        start_token: str,
        *,
        max_pages: int = 200,
        scan_id: int | None = None,
    ) -> AsyncIterator[ParsedBand]:
        """Yield every followed band after `start_token`, to the end of the list."""
        token: str | None = start_token
        for _ in range(max_pages):
            if not token:
                return
            bands, last_token, more = await self.fetch_page(fan_id, token, scan_id=scan_id)
            for band in bands:
                yield band
            if not more or not last_token or last_token == token:
                return
            token = last_token
            if self._delay:
                await asyncio.sleep(self._delay)
