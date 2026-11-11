import asyncio
import time
from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.providers import logger
from src.structs.enums import CacheKeys


_GCRA = """
local now = tonumber(ARGV[1])
local interval = tonumber(ARGV[2])
local window = tonumber(ARGV[3])
local full_at = math.max(tonumber(redis.call('GET', KEYS[1]) or now), now)
local next_full_at = full_at + interval
if next_full_at - window > now then
    return {0, 0, math.ceil((next_full_at - window - now) / 1000000)}
end
redis.call('SET', KEYS[1], string.format('%d', next_full_at), 'PX',
    math.ceil((next_full_at - now) / 1000))
return {1, math.floor((now + window - next_full_at) / interval),
    math.ceil((next_full_at - now) / 1000000)}
"""


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
    now = now_ms * 1000 if now_ms is not None else time.time_ns() // 1000
    window = window_seconds * 1_000_000

    try:
        async with asyncio.timeout(timeout_seconds):
            allowed, remaining, reset = await redis.register_script(_GCRA)(
                keys=[CacheKeys.RATE_LIMIT.format(client=client)],
                args=[now, max(1, window // limit), window],
            )
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

    return RateLimitResult(
        allowed=bool(allowed),
        limit=limit,
        remaining=int(remaining),
        reset=max(1, int(reset)),
    )
