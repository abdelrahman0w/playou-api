import asyncio
import contextlib
from collections.abc import Awaitable
from collections.abc import Callable
from datetime import UTC
from datetime import datetime
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.actions import sync as sync_actions
from src.controllers import library as library_controller
from src.providers import logger
from src.providers import monitor_job
from src.services import OAuthPlatform
from src.settings import settings
from src.structs.enums import Platforms
from src.structs.enums import SyncNudges


WORKER = "sync_worker"

Key = tuple[SyncNudges, UUID]


class SyncWorker:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        redis: Redis,
        waiting: Redis,
        platforms: dict[Platforms, OAuthPlatform],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._clock = clock
        self._session_factory = session_factory
        self._redis = redis
        self._waiting = waiting
        self._platforms = platforms
        self._slots = asyncio.Semaphore(settings.worker.concurrency)
        self._running: dict[Key, asyncio.Task[None]] = {}
        self._again: set[Key] = set()

    async def handle(self, kind: SyncNudges, user_id: UUID) -> None:
        now = self._clock()
        match kind:
            case SyncNudges.PUSH:
                await library_controller.push_changes(
                    self._session_factory,
                    self._platforms,
                    user_id=user_id,
                    now=now,
                )
            case SyncNudges.COPY:
                await library_controller.copy_now(
                    self._session_factory,
                    self._redis,
                    self._platforms,
                    user_id=user_id,
                    now=now,
                )
            case SyncNudges.IMPORT:
                await library_controller.import_now(
                    self._session_factory,
                    self._platforms,
                    user_id=user_id,
                    now=now,
                )

    def take(self, kind: SyncNudges, user_id: UUID) -> None:
        key = (kind, user_id)
        if key in self._running:
            self._again.add(key)
            return

        self._running[key] = asyncio.create_task(self._work(key))

    async def _work(self, key: Key) -> None:
        try:
            while True:
                self._again.discard(key)
                async with self._slots:
                    try:
                        await self.handle(*key)
                    except Exception as error:
                        logger.exception(
                            "[Worker] Nudge Failed",
                            exc_info=error,
                            kind=key[0],
                            user_id=str(key[1]),
                        )
                if key not in self._again:
                    break
        finally:
            del self._running[key]

    async def sweep(self) -> None:
        now = self._clock()
        sweeps: list[tuple[str, Callable[[], Awaitable[object]]]] = [
            (
                "push",
                lambda: sync_actions.push_pending(
                    self._session_factory,
                    self._platforms,
                    now=now,
                ),
            ),
            (
                "import",
                lambda: sync_actions.run_imports(
                    self._session_factory,
                    self._platforms,
                    now=now,
                ),
            ),
            (
                "copy",
                lambda: sync_actions.run_copies(
                    self._session_factory,
                    self._redis,
                    self._platforms,
                    now=now,
                ),
            ),
        ]
        for name, run in sweeps:
            try:
                await run()
            except Exception as error:
                logger.exception(
                    "[Worker] Sweep Failed",
                    exc_info=error,
                    sweep=name,
                )

    async def _beat(self, stop: asyncio.Event) -> None:
        worker = settings.worker
        while not stop.is_set():
            try:
                await sync_actions.beat(
                    self._redis,
                    seconds=worker.heartbeat_seconds * 3,
                )
            except RedisError:
                logger.warning("[Worker] Heartbeat Failed - Redis Is Unavailable")
            if worker.health_file is not None:
                worker.health_file.touch()
            await _wait(stop, worker.heartbeat_seconds)

    async def _sweep(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            with monitor_job(WORKER, 60):
                await self.sweep()
            await _wait(stop, settings.worker.sweep_seconds)

    async def _listen(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                nudge = await sync_actions.next_nudge(
                    self._waiting,
                    wait_seconds=settings.worker.wait_seconds,
                )
            except RedisError:
                logger.warning("[Worker] Listening Failed - Redis Is Unavailable")
                await _wait(stop, 1)
                continue

            if nudge is not None:
                self.take(*nudge)

    async def run(self, stop: asyncio.Event) -> None:
        logger.info(
            "[Worker] Started",
            concurrency=settings.worker.concurrency,
            sweep_seconds=settings.worker.sweep_seconds,
        )
        loops = [
            asyncio.create_task(loop(stop))
            for loop in (self._beat, self._sweep, self._listen)
        ]
        await stop.wait()

        for loop in loops:
            loop.cancel()
        await asyncio.gather(*loops, return_exceptions=True)
        with contextlib.suppress(RedisError):
            await sync_actions.stop_beating(self._redis)
        await asyncio.gather(*self._running.values(), return_exceptions=True)

        logger.info("[Worker] Stopped")


async def _wait(stop: asyncio.Event, seconds: float) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=seconds)
