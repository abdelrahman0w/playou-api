import math

from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.exceptions import PlatformRateLimitedError
from src.providers import logger
from src.structs.enums import CacheKeys
from src.structs.enums import Platforms


class PlatformPause:
    def __init__(
        self,
        redis: Redis,
        platform: Platforms,
        *,
        name: str,
    ) -> None:
        self._redis = redis
        self._key = CacheKeys.PLATFORM_PAUSED.format(platform=platform)
        self._name = name

    def _limited(self, seconds: float) -> PlatformRateLimitedError:
        wait = max(1, math.ceil(seconds))

        return PlatformRateLimitedError(
            f"{self._name} is limiting the requests, try again in {wait} seconds",
            retry_after_seconds=wait,
        )

    async def check(self) -> None:
        try:
            left = await self._redis.pttl(self._key)
        except RedisError:
            return

        if left > 0:
            raise self._limited(left / 1000)

    async def pause(self, seconds: int) -> PlatformRateLimitedError:
        milliseconds = max(1, seconds) * 1000
        try:
            await self._redis.set(self._key, "1", px=milliseconds, nx=True)
            await self._redis.pexpire(self._key, milliseconds, gt=True)
        except RedisError:
            pass

        logger.warning(
            "[Platforms] Paused - Rate Limited",
            platform=self._name,
            seconds=seconds,
        )

        return self._limited(seconds)
