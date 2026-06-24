import logging

from redis import Redis as SyncRedis
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import Settings, get_settings
from app.core.exceptions import DependencyUnavailableError

logger = logging.getLogger(__name__)

def get_redis_client(settings: Settings | None = None) -> Redis:
    current_settings = settings or get_settings()

    return Redis.from_url(
        current_settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
    )

def get_sync_redis_client(settings: Settings | None = None) -> SyncRedis:
    current_settings = settings or get_settings()

    return SyncRedis.from_url(
        current_settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
    )

async def ensure_redis_available(client: Redis | None = None) -> Redis:
    current_client = client or get_redis_client()

    try:
        await current_client.ping()
    except RedisError as exc:
        await current_client.aclose()
        logger.warning("Redis is unavailable for the current request.")
        raise DependencyUnavailableError(
            "Rate limiting service is temporarily unavailable."
        ) from exc

    return current_client

async def close_redis_client() -> None:
    return None
