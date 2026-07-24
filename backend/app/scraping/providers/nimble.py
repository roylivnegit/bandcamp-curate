"""Nimble v2 provider — the sole registered scraper for now.

POSTs to `{base}/extract` with Bearer auth and (optionally) a server-side `parser`
definition; reads structured output from `data.parsing.entities`. Maps Nimble's HTTP
status codes onto the shared exception hierarchy so the gateway can run the waterfall:

    401  → AuthError       (fail fast; bad key)
    402  → QuotaExhausted  (budget/trial gone; open circuit, fall through)
    429  → RateLimited     (back off via retry_after / X-RateLimit-Reset)
    5xx  → ProviderError   (transient; retry then fall through)

The API key is read once from settings and sent only in the Authorization header —
never logged, never included in exceptions.
"""

import time
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.scraping.base import (
    AuthError,
    FetchRequest,
    FetchResult,
    ProviderError,
    QuotaExhausted,
    RateLimited,
    ScraperProvider,
)


class NimbleProvider(ScraperProvider):
    name = "nimble"
    priority = 10
    cost_per_request = 1.0  # relative unit; refine once real pricing is known

    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
        timeout: float = 120.0,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client
        self._timeout = timeout

    @property
    def _endpoint(self) -> str:
        return f"{self._settings.nimble_base_url.rstrip('/')}/extract"

    def _headers(self) -> dict[str, str]:
        # Bearer token is the only place the key is used.
        return {
            "Authorization": f"Bearer {self._settings.nimble_api_key}",
            "Content-Type": "application/json",
        }

    def _build_payload(self, request: FetchRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "url": request.url,
            "render": request.render,
            "country": request.country or self._settings.nimble_country,
        }
        if self._settings.nimble_driver:
            payload["driver"] = self._settings.nimble_driver
        if request.network_capture:
            payload["network_capture"] = request.network_capture
        if request.browser_actions:
            payload["browser_actions"] = request.browser_actions
        if request.parser is not None:
            payload["parse"] = True
            payload["parser"] = request.parser
        payload.update(request.extra)
        return payload

    async def fetch(self, request: FetchRequest) -> FetchResult:
        if not self._settings.nimble_api_key:
            raise AuthError("NIMBLE_API_KEY is not configured")

        payload = self._build_payload(request)
        start = time.monotonic()

        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        owns_client = self._client is None
        try:
            response = await client.post(self._endpoint, json=payload, headers=self._headers())
        except httpx.HTTPError as exc:
            raise ProviderError(f"network error: {exc.__class__.__name__}") from exc
        finally:
            if owns_client:
                await client.aclose()

        latency_ms = int((time.monotonic() - start) * 1000)
        self._raise_for_status(response)
        return self._parse_response(request, response, latency_ms)

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        for header in ("Retry-After", "retry_after", "X-RateLimit-Reset"):
            if header in response.headers:
                try:
                    return float(response.headers[header])
                except ValueError:
                    continue
        try:
            body = response.json()
            err = body.get("error") if isinstance(body, dict) else None
            if isinstance(err, dict) and "retry_after" in err:
                return float(err["retry_after"])
        except (ValueError, TypeError):
            pass
        return None

    def _raise_for_status(self, response: httpx.Response) -> None:
        code = response.status_code
        if code == 200:
            return
        if code == 401:
            raise AuthError("Nimble rejected the API key (401)")
        if code == 402:
            raise QuotaExhausted("Nimble budget/credits exhausted (402)")
        if code == 429:
            raise RateLimited("Nimble rate limit (429)", retry_after=self._retry_after(response))
        raise ProviderError(f"Nimble error (HTTP {code})", status_code=code)

    @staticmethod
    def _quota_remaining(response: httpx.Response) -> int | None:
        val = response.headers.get("X-RateLimit-Remaining")
        if val is None:
            return None
        try:
            return int(val)
        except ValueError:
            return None

    def _parse_response(
        self, request: FetchRequest, response: httpx.Response, latency_ms: int
    ) -> FetchResult:
        body = response.json()
        data = body.get("data", body) if isinstance(body, dict) else {}

        parsing = data.get("parsing") if isinstance(data, dict) else None
        parsing_status: str | None = None
        entities: Any | None = None
        if isinstance(parsing, dict):
            parsing_status = parsing.get("status")
            entities = parsing.get("entities")

        return FetchResult(
            url=request.url,
            provider=self.name,
            status_code=response.status_code,
            ok=True,
            parsing_status=parsing_status,
            entities=entities,
            html=data.get("html") if isinstance(data, dict) else None,
            raw=data if isinstance(data, dict) else None,
            quota_remaining=self._quota_remaining(response),
            latency_ms=latency_ms,
        )

    async def health(self) -> bool:
        return bool(self._settings.nimble_api_key)
