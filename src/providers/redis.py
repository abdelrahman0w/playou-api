from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialWithJitterBackoff

from src.settings import settings
from src.utils import Singleton


def make_redis(*, socket_timeout: float | None = None) -> Redis:
    redis = settings.redis

    return Redis(
        host=redis.host,
        port=redis.port,
        db=redis.db,
        password=redis.password.get_secret_value() if redis.password else None,
        decode_responses=True,
        socket_timeout=socket_timeout or redis.timeout_seconds,
        socket_connect_timeout=redis.connect_timeout_seconds,
        retry=Retry(
            ExponentialWithJitterBackoff(base=0.01, cap=0.1),
            redis.retries,
        ),
        health_check_interval=redis.health_check_seconds,
        max_connections=redis.max_connections,
    )


class RedisConnection(Singleton[Redis]):
    @classmethod
    def create(cls) -> Redis:
        return make_redis()

    @classmethod
    async def connect(cls, instance: Redis) -> None:
        await instance.ping()

    @classmethod
    async def dispose(cls, instance: Redis) -> None:
        await instance.aclose()
