"""Async token-bucket rate limiter + concurrency cap.

Keeps our request rate well under Nimble's ceiling (be a good citizen and control
spend). One shared instance is acquired around every provider call by the gateway.
"""

import asyncio
import time


class RateLimiter:
    def __init__(self, max_qps: float, max_concurrency: int) -> None:
        self._rate = max(max_qps, 0.01)
        self._capacity = max(max_qps, 1.0)
        self._tokens = self._capacity
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(max(max_concurrency, 1))

    async def _acquire_token(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                self._tokens = min(
                    self._capacity, self._tokens + (now - self._updated) * self._rate
                )
                self._updated = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                deficit = 1.0 - self._tokens
                wait = deficit / self._rate
            await asyncio.sleep(wait)

    class _Slot:
        def __init__(self, limiter: "RateLimiter") -> None:
            self._limiter = limiter

        async def __aenter__(self) -> "RateLimiter._Slot":
            await self._limiter._semaphore.acquire()
            try:
                await self._limiter._acquire_token()
            except BaseException:
                self._limiter._semaphore.release()
                raise
            return self

        async def __aexit__(self, *exc: object) -> None:
            self._limiter._semaphore.release()

    def slot(self) -> "RateLimiter._Slot":
        """`async with limiter.slot():` — bounds both QPS and concurrency."""
        return self._Slot(self)
