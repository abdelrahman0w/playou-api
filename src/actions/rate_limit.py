import asyncio
import math
import time
import uuid
from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.providers import logger
from src.structs.enums import CacheKeys


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    reset: int


async def hit(
    redis: Redis,
    client: str,
    *,
    limit: int,
    window_seconds: int,
    timeout_seconds: float = 0.5,
    now_ms: int | None = None,
) -> RateLimitResult:
    now = now_ms if now_ms is not None else time.time_ns() // 1_000_000
    window_ms = window_seconds * 1000
    key = CacheKeys.RATE_LIMIT.format(client=client)
    member = f"{now}-{uuid.uuid4().hex[:12]}"

    try:
        async with asyncio.timeout(timeout_seconds):
            async with redis.pipeline(transaction=True) as pipeline:
                pipeline.zremrangebyscore(key, 0, now - window_ms)
                pipeline.zadd(key, {member: now})
                pipeline.zremrangebyrank(key, 0, -(limit + 2))
                pipeline.zcard(key)
                pipeline.zrange(key, -limit, -limit, withscores=True)
                pipeline.zrange(key, 0, 0, withscores=True)
                pipeline.pexpire(key, window_ms)
                _, _, _, count, blocking, oldest, _ = await pipeline.execute()
    except RedisError, TimeoutError:
        logger.warning(
            "[Rate Limiting] Skipping - Redis Is Unavailable",
        )

        return RateLimitResult(
            allowed=True,
            limit=limit,
            remaining=limit,
            reset=window_seconds,
        )

    allowed = count <= limit
    frees_at = (oldest if allowed else blocking)[0][1] + window_ms

    return RateLimitResult(
        allowed=allowed,
        limit=limit,
        remaining=max(limit - count, 0),
        reset=max(1, math.ceil((frees_at - now) / 1000)),
    )
