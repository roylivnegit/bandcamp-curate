"""Per-provider circuit breaker.

Opens after repeated failures (or immediately on a quota-exhausted signal) so the
gateway stops hammering a dead provider and falls through to the next one. Half-opens
after a cooldown to probe recovery.
"""

import time
from enum import StrEnum


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(self, fail_max: int = 3, reset_timeout: float = 60.0) -> None:
        self.fail_max = fail_max
        self.reset_timeout = reset_timeout
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> CircuitState:
        if self._opened_at is None:
            return CircuitState.CLOSED
        if (time.monotonic() - self._opened_at) >= self.reset_timeout:
            return CircuitState.HALF_OPEN
        return CircuitState.OPEN

    def allow(self) -> bool:
        """Whether a request may be attempted right now."""
        return self.state != CircuitState.OPEN

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.fail_max:
            self.open()

    def open(self) -> None:
        """Force the circuit open (e.g. on a hard quota-exhausted signal)."""
        self._opened_at = time.monotonic()
