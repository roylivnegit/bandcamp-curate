"""Usage sink — records one row per scraper attempt (powers cost/usage dashboard)."""

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass(slots=True)
class UsageEvent:
    provider: str
    ok: bool
    status_code: int | None = None
    cost: float = 0.0
    quota_remaining: int | None = None
    latency_ms: int | None = None
    url: str | None = None
    parser: str | None = None


class UsageSink(Protocol):
    async def record(self, event: UsageEvent) -> None: ...


class NullUsageSink:
    def __init__(self) -> None:
        self.events: list[UsageEvent] = []

    async def record(self, event: UsageEvent) -> None:
        self.events.append(event)


class DbUsageSink:
    """Persists usage events to the `provider_usage` table."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def record(self, event: UsageEvent) -> None:
        from app.db.models import ProviderUsage

        async with self._sessionmaker() as session:
            session.add(
                ProviderUsage(
                    provider=event.provider,
                    ok=event.ok,
                    status_code=event.status_code,
                    cost=event.cost,
                    quota_remaining=event.quota_remaining,
                    latency_ms=event.latency_ms,
                    url=event.url,
                    parser=event.parser,
                )
            )
            await session.commit()
