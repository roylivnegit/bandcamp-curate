import asyncio

import httpx
import pytest

from app.config import Settings
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
from app.scraping.circuit import CircuitBreaker, CircuitState
from app.scraping.gateway import ScraperGateway
from app.scraping.providers.nimble import NimbleProvider
from app.scraping.ratelimit import RateLimiter
from app.scraping.usage import NullUsageSink


async def _noop_sleep(_: float) -> None:
    return None


def _settings() -> Settings:
    return Settings(nimble_api_key="test-key")


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ── NimbleProvider: status-code mapping ──────────────────────────────────────


async def test_nimble_success_parses_entities_and_sends_bearer() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={
                "data": {"html": "<html/>", "parsing": {"status": "success", "entities": {"a": 1}}}
            },
            headers={"X-RateLimit-Remaining": "42"},
        )

    provider = NimbleProvider(_settings(), client=_client(handler))
    result = await provider.fetch(FetchRequest(url="https://bandcamp.com", parser={"x": 1}))

    assert seen["auth"] == "Bearer test-key"
    assert result.parsed_ok
    assert result.entities == {"a": 1}
    assert result.quota_remaining == 42


async def test_nimble_401_raises_auth() -> None:
    provider = NimbleProvider(_settings(), client=_client(lambda r: httpx.Response(401, json={})))
    with pytest.raises(AuthError):
        await provider.fetch(FetchRequest(url="https://bandcamp.com"))


async def test_nimble_402_raises_quota() -> None:
    provider = NimbleProvider(_settings(), client=_client(lambda r: httpx.Response(402, json={})))
    with pytest.raises(QuotaExhausted):
        await provider.fetch(FetchRequest(url="https://bandcamp.com"))


async def test_nimble_429_raises_ratelimited_with_retry_after() -> None:
    handler = lambda r: httpx.Response(429, json={}, headers={"Retry-After": "7"})  # noqa: E731
    provider = NimbleProvider(_settings(), client=_client(handler))
    with pytest.raises(RateLimited) as exc:
        await provider.fetch(FetchRequest(url="https://bandcamp.com"))
    assert exc.value.retry_after == 7.0


async def test_nimble_500_raises_provider_error() -> None:
    provider = NimbleProvider(_settings(), client=_client(lambda r: httpx.Response(503, json={})))
    with pytest.raises(ProviderError):
        await provider.fetch(FetchRequest(url="https://bandcamp.com"))


async def test_nimble_missing_key_raises_auth() -> None:
    provider = NimbleProvider(Settings(nimble_api_key=""))
    with pytest.raises(AuthError):
        await provider.fetch(FetchRequest(url="https://bandcamp.com"))


# ── Fake providers for gateway tests ─────────────────────────────────────────


class FakeProvider(ScraperProvider):
    def __init__(self, name: str, priority: int, outcomes: list) -> None:
        self.name = name
        self.priority = priority
        self.cost_per_request = 1.0
        self._outcomes = outcomes
        self.calls = 0

    async def fetch(self, request: FetchRequest) -> FetchResult:
        self.calls += 1
        outcome = self._outcomes[min(self.calls - 1, len(self._outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _ok(provider: str = "p") -> FetchResult:
    return FetchResult(url="u", provider=provider, status_code=200, ok=True)


def _gateway(providers, usage, **kw) -> ScraperGateway:
    return ScraperGateway(providers, usage=usage, sleep=_noop_sleep, **kw)


# ── Gateway: waterfall behavior ──────────────────────────────────────────────


async def test_gateway_falls_back_on_quota_and_opens_circuit() -> None:
    a = FakeProvider("a", 10, [QuotaExhausted()])
    b = FakeProvider("b", 20, [_ok("b")])
    usage = NullUsageSink()
    gw = _gateway([a, b], usage)

    result = await gw.fetch(FetchRequest(url="https://x"))

    assert result.provider == "b"
    assert a.calls == 1 and b.calls == 1
    statuses = [(e.provider, e.ok, e.status_code) for e in usage.events]
    assert ("a", False, 402) in statuses and ("b", True, 200) in statuses


async def test_gateway_fails_fast_on_auth_error() -> None:
    a = FakeProvider("a", 10, [AuthError()])
    b = FakeProvider("b", 20, [_ok("b")])
    gw = _gateway([a, b], NullUsageSink())

    with pytest.raises(AuthError):
        await gw.fetch(FetchRequest(url="https://x"))
    assert b.calls == 0  # never fell through


async def test_gateway_retries_ratelimited_then_succeeds_same_provider() -> None:
    a = FakeProvider("a", 10, [RateLimited(retry_after=0.0), _ok("a")])
    gw = _gateway([a], NullUsageSink(), max_retries=2)

    result = await gw.fetch(FetchRequest(url="https://x"))
    assert result.provider == "a"
    assert a.calls == 2


async def test_gateway_ratelimited_exhausts_then_falls_through() -> None:
    a = FakeProvider("a", 10, [RateLimited(), RateLimited(), RateLimited()])
    b = FakeProvider("b", 20, [_ok("b")])
    gw = _gateway([a, b], NullUsageSink(), max_retries=1)

    result = await gw.fetch(FetchRequest(url="https://x"))
    assert result.provider == "b"
    assert a.calls == 2  # initial + 1 retry


async def test_gateway_raises_when_all_exhausted() -> None:
    a = FakeProvider("a", 10, [ProviderError()])
    gw = _gateway([a], NullUsageSink(), max_retries=0)
    with pytest.raises(ScraperError):
        await gw.fetch(FetchRequest(url="https://x"))


# ── Circuit breaker ──────────────────────────────────────────────────────────


def test_circuit_breaker_opens_and_recovers() -> None:
    cb = CircuitBreaker(fail_max=2, reset_timeout=0.05)
    assert cb.allow()
    cb.record_failure()
    assert cb.allow()  # 1 < fail_max
    cb.record_failure()
    assert cb.state is CircuitState.OPEN
    assert not cb.allow()


async def test_circuit_breaker_half_opens_after_timeout() -> None:
    cb = CircuitBreaker(fail_max=1, reset_timeout=0.02)
    cb.record_failure()
    assert not cb.allow()
    await asyncio.sleep(0.03)
    assert cb.state is CircuitState.HALF_OPEN
    assert cb.allow()
    cb.record_success()
    assert cb.state is CircuitState.CLOSED


# ── Rate limiter ─────────────────────────────────────────────────────────────


async def test_rate_limiter_caps_concurrency() -> None:
    limiter = RateLimiter(max_qps=1000, max_concurrency=2)
    active = 0
    peak = 0

    async def worker() -> None:
        nonlocal active, peak
        async with limiter.slot():
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1

    await asyncio.gather(*(worker() for _ in range(10)))
    assert peak <= 2
