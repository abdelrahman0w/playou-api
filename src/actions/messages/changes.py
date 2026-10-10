from collections.abc import Iterable
from uuid import UUID

from redis.asyncio import Redis

from src.actions.changes import LISTEN_SECONDS
from src.actions.changes import UserChanges
from src.actions.changes import announce_to
from src.providers import make_redis
from src.structs.enums import CacheKeys
from src.utils import Singleton


class MessageChanges(UserChanges):
    def __init__(self, redis: Redis) -> None:
        super().__init__(redis, CacheKeys.MESSAGES_CHANGED)


async def announce(redis: Redis, user_ids: Iterable[UUID]) -> None:
    for user_id in set(user_ids):
        await announce_to(redis, CacheKeys.MESSAGES_CHANGED, user_id)


class MessageListener(Singleton[MessageChanges]):
    @classmethod
    def create(cls) -> MessageChanges:
        return MessageChanges(make_redis(socket_timeout=LISTEN_SECONDS + 5))

    @classmethod
    async def connect(cls, instance: MessageChanges) -> None:
        await instance.redis.ping()
        instance.start()

    @classmethod
    async def dispose(cls, instance: MessageChanges) -> None:
        await instance.stop()
        await instance.redis.aclose()
