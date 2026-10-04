import math
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from datetime import time
from datetime import timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.exceptions import PlatformRateLimitedError
from src.exceptions import QuotaExhaustedError
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


PACIFIC = ZoneInfo("America/Los_Angeles")
TWO_DAYS = 2 * 24 * 60 * 60

_charged: ContextVar[UUID | None] = ContextVar("charged", default=None)


@contextmanager
def charged_to(account_id: UUID) -> Iterator[None]:
    token = _charged.set(account_id)
    try:
        yield
    finally:
        _charged.reset(token)


def next_midnight(now: datetime) -> datetime:
    local = now.astimezone(PACIFIC)

    return datetime.combine(local.date() + timedelta(days=1), time(), PACIFIC)


class Quota:
    def __init__(
        self,
        redis: Redis,
        platform: Platforms,
        *,
        daily: int,
        name: str,
        per_account: int | None = None,
    ) -> None:
        self._redis = redis
        self._platform = platform
        self._daily = daily
        self._per_account = per_account
        self._name = name

    def _key(self, now: datetime, account_id: UUID | None = None) -> str:
        day = now.astimezone(PACIFIC).date().isoformat()
        key = CacheKeys.PLATFORM_QUOTA.format(platform=self._platform, day=day)

        return f"{key}:{account_id}" if account_id else key

    def _exhausted(
        self, now: datetime, *, account: bool = False
    ) -> QuotaExhaustedError:
        whose = "this account's share of " if account else ""

        return QuotaExhaustedError(
            f"{whose}{self._name}'s daily quota is spent, "
            "it is back after midnight Pacific time",
            retry_at=next_midnight(now),
        )

    async def _take(self, key: str, units: int, limit: int) -> bool:
        used = await self._redis.incrby(key, units)
        if used == units:
            await self._redis.expire(key, TWO_DAYS)
        if used <= limit:
            return True

        await self._redis.decrby(key, units)

        return False

    async def reserve(self, units: int, *, now: datetime | None = None) -> None:
        moment = now or datetime.now(PACIFIC)
        account_id = _charged.get()
        try:
            if account_id and self._per_account is not None:
                personal = self._key(moment, account_id)
                if not await self._take(personal, units, self._per_account):
                    raise self._exhausted(moment, account=True)
                if not await self._take(self._key(moment), units, self._daily):
                    await self._redis.decrby(personal, units)
                    raise self._exhausted(moment)

                return

            if not await self._take(self._key(moment), units, self._daily):
                raise self._exhausted(moment)
        except RedisError:
            return

    async def spend(self, *, now: datetime | None = None) -> QuotaExhaustedError:
        moment = now or datetime.now(PACIFIC)
        try:
            await self._redis.set(self._key(moment), self._daily, ex=TWO_DAYS)
        except RedisError:
            pass

        logger.warning(
            "[Platforms] Quota Spent",
            platform=self._name,
        )

        return self._exhausted(moment)

    async def used(
        self,
        *,
        now: datetime | None = None,
        account_id: UUID | None = None,
    ) -> int:
        try:
            value = await self._redis.get(
                self._key(now or datetime.now(PACIFIC), account_id),
            )
        except RedisError:
            return 0

        return int(value or 0)
