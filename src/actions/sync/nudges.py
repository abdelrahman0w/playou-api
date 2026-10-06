from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.structs.enums import CacheKeys
from src.structs.enums import SyncNudges


async def nudge(
    redis: Redis,
    kind: SyncNudges,
    user_id: UUID,
) -> bool:
    try:
        if not await redis.exists(CacheKeys.SYNC_WORKER_ALIVE):
            return False

        await redis.rpush(CacheKeys.SYNC_NUDGES, f"{kind}:{user_id}")
    except RedisError:
        return False

    return True


async def next_nudge(
    redis: Redis,
    *,
    wait_seconds: int,
) -> tuple[SyncNudges, UUID] | None:
    popped = await redis.blpop([CacheKeys.SYNC_NUDGES], timeout=wait_seconds)
    if popped is None:
        return None

    kind, _, user_id = str(popped[1]).partition(":")
    try:
        return SyncNudges(kind), UUID(user_id)
    except ValueError:
        return None


async def beat(redis: Redis, *, seconds: int) -> None:
    await redis.set(CacheKeys.SYNC_WORKER_ALIVE, "1", ex=seconds)


async def stop_beating(redis: Redis) -> None:
    await redis.delete(CacheKeys.SYNC_WORKER_ALIVE)
