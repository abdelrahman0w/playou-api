import asyncio
import contextlib
from collections.abc import Iterator
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.providers import logger
from src.providers import make_redis
from src.structs.enums import CacheKeys
from src.utils import Singleton


LISTEN_SECONDS = 10
RECONNECT_SECONDS = 1


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


class PlaybackChanges:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis
        self._waiting: dict[UUID, set[asyncio.Event]] = {}
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._listen())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()

            with contextlib.suppress(asyncio.CancelledError):
                await self._task

            self._task = None

        self._wake_all()

    @contextlib.contextmanager
    def watch(self, user_id: UUID) -> Iterator[asyncio.Event]:
        changed = asyncio.Event()
        self._waiting.setdefault(user_id, set()).add(changed)

        try:
            yield changed
        finally:
            waiting = self._waiting.get(user_id)
            if waiting is not None:
                waiting.discard(changed)

                if not waiting:
                    del self._waiting[user_id]

    def _wake(self, user_id: str) -> None:
        try:
            waiting = self._waiting.get(UUID(user_id), ())
        except ValueError:
            return

        for changed in waiting:
            changed.set()

    def _wake_all(self) -> None:
        for waiting in self._waiting.values():
            for changed in waiting:
                changed.set()

    async def _listen(self) -> None:
        away = False
        while True:
            try:
                async with self.redis.pubsub() as pubsub:
                    await pubsub.subscribe(CacheKeys.PLAYBACK_CHANGED)
                    if away:
                        away = False
                        self._wake_all()
                    while True:
                        message = await pubsub.get_message(
                            ignore_subscribe_messages=True,
                            timeout=LISTEN_SECONDS,
                        )
                        if message is not None:
                            self._wake(str(message["data"]))
            except asyncio.CancelledError:
                raise
            except Exception as error:
                if not away:
                    logger.warning(
                        "[Playback] Listening For Changes Failed - Trying Again",
                        error=repr(error),
                    )
                away = True
                await asyncio.sleep(RECONNECT_SECONDS)


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
