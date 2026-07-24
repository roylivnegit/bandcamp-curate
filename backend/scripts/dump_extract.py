"""Dump a full Nimble v2 /extract response to a file for offline parser authoring.

Usage:
    python -m scripts.dump_extract <url> <out.json> [capture_substr] [--scroll]

Writes the provider `data` payload (html, network_capture, etc.) as JSON so we can
inspect Bandcamp's real response shape without repeated credit spend.
"""

import asyncio
import json
import sys

from app.config import get_settings
from app.scraping.base import FetchRequest
from app.scraping.providers.nimble import NimbleProvider


async def main() -> int:
    settings = get_settings()
    if not settings.nimble_api_key:
        print("NIMBLE_API_KEY not set. Aborting.")
        return 2
    if len(sys.argv) < 3:
        print("usage: python -m scripts.dump_extract <url> <out.json> [capture_substr] [--scroll]")
        return 2

    url, out = sys.argv[1], sys.argv[2]
    rest = sys.argv[3:]
    scroll = "--scroll" in rest
    capture = next((a for a in rest if not a.startswith("--")), None)

    network_capture = [{"url": {"type": "contains", "value": capture}}] if capture else None
    browser_actions = [{"name": "auto_scroll"}] if scroll else None

    provider = NimbleProvider(settings, timeout=240.0)
    print(f"POST {provider._endpoint}  url={url}  capture={capture}  scroll={scroll}")
    result = await provider.fetch(
        FetchRequest(
            url=url,
            render=True,
            network_capture=network_capture,
            browser_actions=browser_actions,
        )
    )
    payload = result.raw or {}
    with open(out, "w") as fh:
        json.dump(payload, fh)

    nc = payload.get("network_capture") or []
    captured = sum(len(g.get("results", [])) for g in nc if isinstance(g, dict))
    print(f"HTTP {result.status_code}  html_bytes={len(result.html or '')}  latency={result.latency_ms}ms")
    print(f"top-level data keys: {sorted(payload) if isinstance(payload, dict) else type(payload)}")
    print(f"network_capture groups={len(nc)} captured_results={captured}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
