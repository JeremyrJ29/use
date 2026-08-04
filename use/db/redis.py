from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

import redis.asyncio as aioredis

from use.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None

# All keys are namespaced under "use:"
_NS = "use:"


def get_redis_client() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    client = get_redis_client()
    yield client


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


class RedisCache:
    """
    Thin async cache wrapper around redis.asyncio.

    All keys are stored under the ``use:`` namespace prefix so they are
    easy to identify and bulk-invalidate.
    """

    def __init__(self, client: aioredis.Redis | None = None) -> None:
        self._client = client

    def _client_or_default(self) -> aioredis.Redis:
        return self._client if self._client is not None else get_redis_client()

    def _full_key(self, key: str) -> str:
        """Ensure the ``use:`` namespace prefix."""
        if key.startswith(_NS):
            return key
        return f"{_NS}{key}"

    async def get(self, key: str) -> Any | None:
        """Return deserialised value or None on cache miss / error."""
        try:
            raw = await self._client_or_default().get(self._full_key(key))
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as exc:
            logger.warning("RedisCache.get error key=%s: %s", key, exc)
            return None

    async def set(self, key: str, value: Any, ttl_seconds: int = 3600) -> None:
        """Serialise *value* as JSON and store with the given TTL."""
        try:
            serialised = json.dumps(value, default=str)
            await self._client_or_default().set(
                self._full_key(key), serialised, ex=ttl_seconds
            )
        except Exception as exc:
            logger.warning("RedisCache.set error key=%s: %s", key, exc)

    async def delete(self, key: str) -> None:
        """Delete a single key."""
        try:
            await self._client_or_default().delete(self._full_key(key))
        except Exception as exc:
            logger.warning("RedisCache.delete error key=%s: %s", key, exc)

    async def invalidate_prefix(self, prefix: str) -> None:
        """SCAN + DELETE all keys whose full name starts with ``use:<prefix>``."""
        full_prefix = self._full_key(prefix)
        client = self._client_or_default()
        try:
            cursor = 0
            while True:
                cursor, keys = await client.scan(
                    cursor=cursor, match=f"{full_prefix}*", count=100
                )
                if keys:
                    await client.delete(*keys)
                if cursor == 0:
                    break
        except Exception as exc:
            logger.warning("RedisCache.invalidate_prefix error prefix=%s: %s", prefix, exc)


# Module-level singleton — callers can import this directly or build their
# own instance with a specific client.
cache = RedisCache()
