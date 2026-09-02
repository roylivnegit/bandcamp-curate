"""Route a Bandcamp JSON-API POST through the Nimble gateway.

The pagination XHRs (collection_items, wishlist_items, following_bands, thumbs) can
run either direct-to-Bandcamp (free, but 429s under concurrency) or through Nimble
(proxied IP rotation → no 429s at 40+ concurrent — verified 2026-07-24). Going
through the gateway also means these calls are rate-limited, retried, and logged to
`provider_usage` / counted against the crawl budget, exactly like page renders.

Nimble POST shape (confirmed): render off, `method:"POST"`, JSON `body` string, and
a Content-Type header. The target's JSON response comes back in `data.html`.
"""

import json
from typing import Any, Protocol

from app.scraping.base import FetchRequest


class GatewayFetcher(Protocol):
    async def fetch(self, request: FetchRequest) -> Any: ...


async def post_json_via_nimble(
    gateway: GatewayFetcher, url: str, payload: dict, *, scan_id: int | None = None
) -> dict:
    """POST `payload` to a Bandcamp API `url` through Nimble; return the parsed JSON.

    `scan_id` is attribution-only (see `FetchRequest.scan_id`) — it lets
    `provider_usage` and the per-user crawl budget count these pagination
    fetches against the scan that spent them, same as page renders.
    """
    request = FetchRequest(
        url=url,
        render=False,
        parser_name="bc_api",
        extra={
            "method": "POST",
            "body": json.dumps(payload),
            "headers": {"Content-Type": "application/json"},
        },
        scan_id=scan_id,
    )
    result = await gateway.fetch(request)
    if not result.html:
        raise ValueError(f"empty Nimble response for POST {url}")
    return json.loads(result.html)
