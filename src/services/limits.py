import math
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from datetime import time
from datetime import timedelta
from time import monotonic
from uuid import UUID
from zoneinfo import ZoneInfo

from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.exceptions import PlatformRateLimitedError
from src.exceptions import QuotaExhaustedError
from src.providers import logger
from src.structs.enums import CacheKeys
from src.structs.enums import Platforms


LONG_PAUSE_SECONDS = 10 * 60
UNKNOWN_WAIT_SECONDS = 30


def _unknown(what: str) -> PlatformRateLimitedError:
    return PlatformRateLimitedError(
        f"{what} cannot be checked right now, "
        f"try again in {UNKNOWN_WAIT_SECONDS} seconds",
        retry_after_seconds=UNKNOWN_WAIT_SECONDS,
    )


class PlatformPause:
    closed_when_unknown = False

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
        self._seen: dict[str, float] = {}

    def _limited(self, seconds: float) -> PlatformRateLimitedError:
        wait = max(1, math.ceil(seconds))

        return PlatformRateLimitedError(
            f"{self._name} is limiting the requests, try again in {wait} seconds",
            retry_after_seconds=wait,
        )

    def _key_for(self, group: str | None) -> str:
        return self._key if group is None else f"{self._key}:{group}"

    async def check(self, group: str | None = None) -> None:
        keys = [self._key] if group is None else [self._key, self._key_for(group)]
        now = monotonic()
        seen = max(self._seen.get(key, now) - now for key in keys)

        try:
            shared = max([await self._redis.pttl(key) for key in keys]) / 1000
        except RedisError:
            if seen <= 0 and self.closed_when_unknown:
                raise _unknown(f"{self._name}'s pauses") from None

            shared = 0

        if (left := max(seen, shared)) > 0:
            raise self._limited(left)

    async def pause(
        self,
        seconds: int,
        *,
        group: str | None = None,
        path: str | None = None,
    ) -> PlatformRateLimitedError:
        scoped = group if seconds > LONG_PAUSE_SECONDS else None
        key = self._key_for(scoped)
        milliseconds = max(1, seconds) * 1000
        until = monotonic() + max(1, seconds)
        self._seen[key] = max(self._seen.get(key, until), until)

        try:
            await self._redis.set(key, "1", px=milliseconds, nx=True)
            await self._redis.pexpire(key, milliseconds, gt=True)
        except RedisError:
            pass

        logger.warning(
            "[Platforms] Paused - Rate Limited",
            platform=self._name,
            seconds=seconds,
            path=path,
            paused=scoped or "everything",
        )

        return self._limited(seconds)


PACIFIC = ZoneInfo("America/Los_Angeles")
TWO_DAYS = 2 * 24 * 60 * 60

PUSHES = "push"
FINDS = "find"

_charged: ContextVar[tuple[UUID, str] | None] = ContextVar("charged", default=None)


@contextmanager
def charged_to(account_id: UUID, pool: str = PUSHES) -> Generator[None]:
    token = _charged.set((account_id, pool))
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
        per_account_finds: int | None = None,
    ) -> None:
        self._redis = redis
        self._platform = platform
        self._daily = daily
        self._shares = {PUSHES: per_account, FINDS: per_account_finds}
        self._name = name

    def _key(
        self,
        now: datetime,
        account_id: UUID | None = None,
        pool: str = PUSHES,
    ) -> str:
        day = now.astimezone(PACIFIC).date().isoformat()
        key = CacheKeys.PLATFORM_QUOTA.format(platform=self._platform, day=day)
        if account_id is None:
            return key

        return f"{key}:{account_id}" if pool == PUSHES else f"{key}:{pool}:{account_id}"

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
        charged = _charged.get()
        share = self._shares.get(charged[1]) if charged else None
        try:
            if charged and share is not None:
                personal = self._key(moment, *charged)
                if not await self._take(personal, units, share):
                    raise self._exhausted(moment, account=True)
                if not await self._take(self._key(moment), units, self._daily):
                    await self._redis.decrby(personal, units)
                    raise self._exhausted(moment)

                return

            if not await self._take(self._key(moment), units, self._daily):
                raise self._exhausted(moment)
        except RedisError:
            raise _unknown(f"{self._name}'s quota") from None

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
        pool: str = PUSHES,
    ) -> int:
        try:
            value = await self._redis.get(
                self._key(now or datetime.now(PACIFIC), account_id, pool),
            )
        except RedisError:
            return 0

        return int(value or 0)
