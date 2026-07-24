"""ScraperGateway — the waterfall.

Tries providers in `priority` order. Cache hits short-circuit. Each attempt is
bounded by the shared rate limiter and guarded by a per-provider circuit breaker.
Failures map to fallback behavior:

    AuthError       → fail fast (bad key; fallback won't help)
    QuotaExhausted  → open this provider's circuit, fall to the next
    RateLimited     → back off (retry_after), retry this provider, then fall through
    ProviderError   → record failure, retry this provider, then fall through

Only Nimble is registered today; adding a provider is `providers=[NimbleProvider(),
OtherProvider()]` with no call-site changes.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence

from app.scraping.base import (
    AuthError,
    FetchRequest,
    FetchResult,
    ProviderError,
    QuotaExhausted,
    RateLimited,
    ScraperError,
    ScraperProvider,
)
from app.scraping.cache import NullCache, ResponseCache
from app.scraping.circuit import CircuitBreaker
from app.scraping.ratelimit import RateLimiter
from app.scraping.usage import NullUsageSink, UsageEvent, UsageSink

logger = logging.getLogger("crate_digger.scraping")


class ScraperGateway:
    def __init__(
        self,
        providers: Sequence[ScraperProvider],
        rate_limiter: RateLimiter | None = None,
        cache: ResponseCache | None = None,
        usage: UsageSink | None = None,
        max_retries: int = 2,
        breaker_fail_max: int = 3,
        breaker_reset_timeout: float = 60.0,
        default_backoff: float = 2.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not providers:
            raise ValueError("ScraperGateway requires at least one provider")
        self._providers = sorted(providers, key=lambda p: p.priority)
        self._rate_limiter = rate_limiter or RateLimiter(max_qps=2, max_concurrency=4)
        self._cache = cache or NullCache()
        self._usage = usage or NullUsageSink()
        self._max_retries = max_retries
        self._default_backoff = default_backoff
        self._sleep = sleep
        self._breakers: dict[str, CircuitBreaker] = {
            p.name: CircuitBreaker(breaker_fail_max, breaker_reset_timeout) for p in providers
        }

    async def fetch(self, request: FetchRequest) -> FetchResult:
        cached = await self._cache.get(request)
        if cached is not None:
            return cached

        last_error: ScraperError | None = None
        for provider in self._providers:
            if not provider.supports(request.url):
                continue
            breaker = self._breakers[provider.name]
            if not breaker.allow():
                logger.debug("skipping %s (circuit open)", provider.name)
                continue

            result, err = await self._try_provider(provider, breaker, request)
            if result is not None:
                await self._cache.set(request, result)
                return result
            if isinstance(err, AuthError):
                raise err  # fail fast — no fallback for bad credentials
            last_error = err

        raise ScraperError("all providers exhausted") from last_error

    async def _try_provider(
        self, provider: ScraperProvider, breaker: CircuitBreaker, request: FetchRequest
    ) -> tuple[FetchResult | None, ScraperError | None]:
        """Attempt one provider (with same-provider retries). Returns (result, error)."""
        attempt = 0
        while True:
            try:
                async with self._rate_limiter.slot():
                    result = await provider.fetch(request)
            except AuthError as exc:
                await self._log(provider, request, ok=False, status=401)
                return None, exc
            except QuotaExhausted as exc:
                await self._log(provider, request, ok=False, status=402)
                breaker.open()
                return None, exc
            except RateLimited as exc:
                await self._log(provider, request, ok=False, status=429)
                if attempt < self._max_retries:
                    await self._sleep(exc.retry_after or self._default_backoff)
                    attempt += 1
                    continue
                breaker.record_failure()
                return None, exc
            except ProviderError as exc:
                await self._log(provider, request, ok=False, status=exc.status_code)
                breaker.record_failure()
                if attempt < self._max_retries:
                    await self._sleep(self._default_backoff)
                    attempt += 1
                    continue
                return None, exc

            breaker.record_success()
            await self._log(
                provider,
                request,
                ok=True,
                status=result.status_code,
                cost=provider.cost_per_request,
                quota_remaining=result.quota_remaining,
                latency_ms=result.latency_ms,
            )
            return result, None

    async def _log(
        self,
        provider: ScraperProvider,
        request: FetchRequest,
        *,
        ok: bool,
        status: int | None,
        cost: float = 0.0,
        quota_remaining: int | None = None,
        latency_ms: int | None = None,
    ) -> None:
        try:
            await self._usage.record(
                UsageEvent(
                    provider=provider.name,
                    ok=ok,
                    status_code=status,
                    cost=cost,
                    quota_remaining=quota_remaining,
                    latency_ms=latency_ms,
                    url=request.url,
                    parser=request.parser_name,
                )
            )
        except Exception:  # usage logging must never break a scrape
            logger.exception("failed to record usage event")
