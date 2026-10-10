from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.actions.changes import LISTEN_SECONDS
from src.actions.changes import UserChanges
from src.providers import logger
from src.providers import make_redis
from src.structs.enums import CacheKeys
from src.utils import Singleton


async def announce(
    redis: Redis,
    user_id: UUID,
) -> None:
    try:
        await redis.publish(
            CacheKeys.PLAYBACK_CHANGED,
            str(user_id),
        )
    except RedisError:
        logger.warning(
            "[Playback] Change Not Announced - Redis Is Unavailable",
        )


class PlaybackChanges(UserChanges):
    def __init__(self, redis: Redis) -> None:
        super().__init__(redis, CacheKeys.PLAYBACK_CHANGED)


class PlaybackListener(Singleton[PlaybackChanges]):
    @classmethod
    def create(cls) -> PlaybackChanges:
        return PlaybackChanges(make_redis(socket_timeout=LISTEN_SECONDS + 5))

    @classmethod
    async def connect(cls, instance: PlaybackChanges) -> None:
        await instance.redis.ping()
        instance.start()

    @classmethod
    async def dispose(cls, instance: PlaybackChanges) -> None:
        await instance.stop()
        await instance.redis.aclose()
