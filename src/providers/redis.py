from redis.asyncio import Redis

from src.settings import settings
from src.utils import Singleton


class RedisConnection(Singleton[Redis]):
    @classmethod
    def create(cls) -> Redis:
        redis = settings.redis

        return Redis(
            host=redis.host,
            port=redis.port,
            db=redis.db,
            password=redis.password.get_secret_value() if redis.password else None,
            decode_responses=True,
        )

    @classmethod
    async def connect(cls, instance: Redis) -> None:
        await instance.ping()

    @classmethod
    async def dispose(cls, instance: Redis) -> None:
        await instance.aclose()
