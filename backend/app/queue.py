import asyncio
from urllib.parse import urlparse

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from redis import Redis

from .config import settings

ARQ_QUEUE_BUILDS = "unica-wb:builds"
ARQ_QUEUE_CONTROLS = "unica-wb:controls"

redis_conn = Redis.from_url(settings.redis_url)

_arq_pool: ArqRedis | None = None
_arq_lock = asyncio.Lock()


def _redis_settings_from_url(url: str) -> RedisSettings:
    parsed = urlparse(url)
    db = 0
    if parsed.path and parsed.path != "/":
        try:
            db = int(parsed.path.lstrip("/"))
        except ValueError:
            db = 0
    return RedisSettings(
        host=parsed.hostname or "redis",
        port=parsed.port or 6379,
        database=db,
        username=parsed.username,
        password=parsed.password,
        ssl=parsed.scheme == "rediss",
    )


async def get_arq_pool() -> ArqRedis:
    global _arq_pool
    if _arq_pool is not None:
        return _arq_pool
    async with _arq_lock:
        if _arq_pool is None:
            _arq_pool = await create_pool(_redis_settings_from_url(settings.redis_url))
    return _arq_pool


async def close_arq_pool():
    global _arq_pool
    if _arq_pool is not None:
        await _arq_pool.close()
        _arq_pool = None
