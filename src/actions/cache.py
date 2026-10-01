import asyncio
from collections.abc import Awaitable
from collections.abc import Callable

from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.providers import logger
from src.utils import adapter
from src.utils import single_flight


_refreshing: set[asyncio.Task[None]] = set()


def _fresh_key(key: str) -> str:
    return f"{key}:fresh"


async def _refresh[T](
    redis: Redis,
    key: str,
    produce: Callable[[], Awaitable[T]],
    shape: type[T],
    ttl_seconds: int,
) -> None:
    try:
        body = adapter(shape).dump_json(await produce()).decode()
        await redis.set(key, body, ex=ttl_seconds)
    except Exception as error:
        logger.warning(
            "[Cache] Refresh Failed - Kept The Stale Copy",
            key=key,
            error=repr(error),
        )


async def _refresh_when_stale[T](
    redis: Redis,
    key: str,
    produce: Callable[[], Awaitable[T]],
    shape: type[T],
    *,
    ttl_seconds: int,
    fresh_seconds: int,
) -> None:
    try:
        claimed = await redis.set(
            _fresh_key(key),
            "1",
            ex=fresh_seconds,
            nx=True,
        )
    except RedisError:
        return

    if claimed:
        task = asyncio.create_task(
            _refresh(redis, key, produce, shape, ttl_seconds),
        )
        _refreshing.add(task)
        task.add_done_callback(_refreshing.discard)


async def cached_json[T](
    redis: Redis,
    key: str,
    produce: Callable[[], Awaitable[T]],
    shape: type[T],
    *,
    ttl_seconds: int,
    fresh_seconds: int | None = None,
) -> str:
    try:
        if (cached := await redis.get(key)) is not None:
            if fresh_seconds is not None:
                await _refresh_when_stale(
                    redis,
                    key,
                    produce,
                    shape,
                    ttl_seconds=ttl_seconds,
                    fresh_seconds=fresh_seconds,
                )
            return cached if isinstance(cached, str) else cached.decode()
    except RedisError:
        logger.warning(
            "[Cache] Skipped - Redis Is Unavailable",
            key=key,
        )

    async def produce_and_cache() -> str:
        body = adapter(shape).dump_json(await produce()).decode()

        try:
            await redis.set(key, body, ex=ttl_seconds)

            if fresh_seconds is not None:
                await redis.set(_fresh_key(key), "1", ex=fresh_seconds)
        except RedisError:
            logger.warning(
                "[Cache] Could Not Cache - Redis Is Unavailable",
                key=key,
            )

        return body

    return await single_flight(key, produce_and_cache)
