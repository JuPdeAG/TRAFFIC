"""Redis async client."""
from __future__ import annotations
import logging
import redis.asyncio as aioredis
from traffic_ai.config import settings

logger = logging.getLogger(__name__)
_redis: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """Return a singleton async Redis client."""
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        logger.info("Redis client connected: %s", settings.redis_url)
    return _redis
