"""Live smoke test for the Nimble v2 provider (M1 verification).

Requires NIMBLE_API_KEY in the environment / .env. Does ONE realtime /v2/extract
call against a known Bandcamp URL and prints the outcome. The key is read from
settings and never printed.

    python -m scripts.verify_nimble [url]
"""

import asyncio
import sys

from app.config import get_settings
from app.scraping.base import FetchRequest
from app.scraping.providers.nimble import NimbleProvider

DEFAULT_URL = "https://bandcamp.com"


async def main() -> int:
    settings = get_settings()
    if not settings.nimble_api_key:
        print("NIMBLE_API_KEY is not set — populate .env first. Aborting (no call made).")
        return 2

    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    provider = NimbleProvider(settings)
    print(f"POST {provider._endpoint}  (url={url}, key=***redacted***)")

    result = await provider.fetch(FetchRequest(url=url, render=True))
    print(f"HTTP {result.status_code}  ok={result.ok}  latency={result.latency_ms}ms")
    print(f"parsing_status={result.parsing_status}  quota_remaining={result.quota_remaining}")
    print(f"html_bytes={len(result.html or '')}")
    if result.entities is not None:
        print(f"entities keys: {list(result.entities)[:10] if hasattr(result.entities, '__iter__') else result.entities}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
