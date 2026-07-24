"""Wire a ScraperGateway from settings.

Registers Nimble as the sole provider today. To add a fallback later, append it to
`providers` here — nothing else changes.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.scraping.cache import NullCache, RedisCache, ResponseCache
from app.scraping.gateway import ScraperGateway
from app.scraping.providers.nimble import NimbleProvider
from app.scraping.ratelimit import RateLimiter
from app.scraping.usage import DbUsageSink, NullUsageSink, UsageSink


def build_gateway(
    settings: Settings | None = None,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    redis_client: Any | None = None,
) -> ScraperGateway:
    settings = settings or get_settings()

    providers = [NimbleProvider(settings)]
    # Future fallbacks append here, e.g. providers.append(OtherProvider(...)).

    rate_limiter = RateLimiter(
        max_qps=settings.scraper_max_qps,
        max_concurrency=settings.scraper_max_concurrency,
    )
    cache: ResponseCache = RedisCache(redis_client) if redis_client is not None else NullCache()
    usage: UsageSink = DbUsageSink(sessionmaker) if sessionmaker is not None else NullUsageSink()

    return ScraperGateway(
        providers,
        rate_limiter=rate_limiter,
        cache=cache,
        usage=usage,
        max_retries=settings.scraper_max_retries,
    )
