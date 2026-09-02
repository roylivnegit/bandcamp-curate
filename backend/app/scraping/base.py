"""Provider-agnostic contract for the scraper waterfall.

Every scraping backend (Nimble today, others later) implements `ScraperProvider`.
The gateway talks only to this interface, so adding a provider never touches call
sites. Providers translate backend-specific failures into the exception hierarchy
below, which is what drives the waterfall's fallback decisions.
"""

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

# ── Request / result ─────────────────────────────────────────────────────────


@dataclass(slots=True)
class FetchRequest:
    """A single scrape to perform.

    `parser` is the backend's server-side parser definition (Nimble parsit-ai);
    `parser_name` is a human label used for cache keys and usage logging.
    """

    url: str
    parser_name: str | None = None
    parser: dict[str, Any] | None = None
    render: bool | str = True
    country: str | None = None
    network_capture: list[dict[str, Any]] | None = None
    browser_actions: list[dict[str, Any]] | None = None
    # Escape hatch for provider-specific fields not modeled above.
    extra: dict[str, Any] = field(default_factory=dict)
    # Attribution only — which scan this fetch belongs to, for per-user budget
    # accounting (`provider_usage.scan_id`). Never part of the cache key: the
    # same URL/body should still hit the cache regardless of which scan asks.
    scan_id: int | None = None

    def cache_key(self) -> str:
        key = f"{self.parser_name or 'raw'}::{self.url}"
        # POST pagination shares one URL but varies by body (in `extra`), so fold a
        # digest of `extra` in — otherwise different pages would collide in the cache.
        if self.extra:
            digest = hashlib.sha1(
                json.dumps(self.extra, sort_keys=True, default=str).encode()
            ).hexdigest()[:12]
            key = f"{key}::{digest}"
        return key


@dataclass(slots=True)
class FetchResult:
    """Normalized outcome of a successful fetch."""

    url: str
    provider: str
    status_code: int
    ok: bool
    parsing_status: str | None = None  # "success" | "error" | None
    entities: Any | None = None  # parsed structured data (data.parsing.entities)
    html: str | None = None
    raw: dict[str, Any] | None = None  # full provider `data` payload
    quota_remaining: int | None = None
    latency_ms: int | None = None
    from_cache: bool = False

    @property
    def parsed_ok(self) -> bool:
        return self.ok and self.parsing_status == "success" and self.entities is not None


# ── Exception hierarchy (drives fallback) ────────────────────────────────────


class ScraperError(Exception):
    """Base for all scraper failures."""


class AuthError(ScraperError):
    """Bad/missing credentials (HTTP 401). Fail fast — fallback won't help."""


class QuotaExhausted(ScraperError):
    """Budget/credits exhausted (HTTP 402). Open circuit and fall through."""


class RateLimited(ScraperError):
    """Rate limit hit (HTTP 429). Back off, then retry/fall through."""

    def __init__(self, message: str = "", retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ProviderError(ScraperError):
    """Transient/other provider failure (5xx, network). Retry then fall through."""

    def __init__(self, message: str = "", status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


# ── Provider interface ───────────────────────────────────────────────────────


class ScraperProvider(ABC):
    """A scraping backend. Ordered in the waterfall by `priority` (lower first)."""

    name: str = "provider"
    priority: int = 100
    cost_per_request: float = 0.0

    def supports(self, url: str) -> bool:
        """Whether this provider can handle the URL. Default: everything."""
        return True

    @abstractmethod
    async def fetch(self, request: FetchRequest) -> FetchResult:
        """Perform the fetch or raise a `ScraperError` subclass."""

    async def health(self) -> bool:
        """Lightweight readiness check. Default: assume healthy."""
        return True
