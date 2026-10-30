"""Optional cache for Binance responses.

Redis is tried first when it is reachable. If Redis is
unavailable, an in-memory cache with the same TTL semantics is
used instead, so caching never fails a request. This is a
single-instance cache: distributed invalidation is not a
requirement at the current scale and is documented for later.
"""

import json
import logging
import time
from decimal import Decimal

from app.config import settings

logger = logging.getLogger(__name__)

_memory_cache: dict[str, tuple[float, str]] = {}


def _memory_get(key: str) -> str | None:
    entry = _memory_cache.get(key)
    if entry is None:
        return None
    expires_at, value = entry
    if time.time() > expires_at:
        _memory_cache.pop(key, None)
        return None
    return value


def _memory_set(key: str, value: str, ttl_seconds: int) -> None:
    _memory_cache[key] = (time.time() + ttl_seconds, value)


def _serialise(value) -> str:
    def default(obj):
        if isinstance(obj, Decimal):
            return str(obj)
        return str(obj)

    return json.dumps(value, default=default)


async def cache_get(key: str) -> dict | list | None:
    try:
        import redis.asyncio as redis

        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1)
        raw = await client.get(key)
        await client.aclose()
        if raw is not None:
            return json.loads(raw)
    except Exception as exc:  # noqa: BLE001 - cache must never fail a request
        logger.debug("Redis cache read failed, using memory cache: %s", type(exc).__name__)
    raw = _memory_get(key)
    return json.loads(raw) if raw is not None else None


async def cache_set(key: str, value, ttl_seconds: int) -> None:
    payload = _serialise(value)
    try:
        import redis.asyncio as redis

        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1)
        await client.setex(key, ttl_seconds, payload)
        await client.aclose()
        return
    except Exception as exc:  # noqa: BLE001 - cache must never fail a request
        logger.debug("Redis cache write failed, using memory cache: %s", type(exc).__name__)
    _memory_set(key, payload, ttl_seconds)


def clear_memory_cache() -> None:
    _memory_cache.clear()
