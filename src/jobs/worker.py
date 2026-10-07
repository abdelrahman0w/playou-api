import asyncio
import contextlib
import time
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
        self._push_slots = asyncio.Semaphore(settings.worker.push_concurrency)
        self._running: dict[Key, asyncio.Task[None]] = {}
        self._again: set[Key] = set()
        self._listened_at = time.monotonic()

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
                slots = self._push_slots if key[0] is SyncNudges.PUSH else self._slots
                async with slots:
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

    async def sweep_pushes(self) -> None:
        await self._sweep_one(
            "push",
            lambda: sync_actions.push_pending(
                self._session_factory,
                self._platforms,
                now=self._clock(),
            ),
        )

    async def sweep_imports(self) -> None:
        await self._sweep_one(
            "import",
            lambda: sync_actions.run_imports(
                self._session_factory,
                self._platforms,
                now=self._clock(),
            ),
        )

    async def sweep_copies(self) -> None:
        await self._sweep_one(
            "copy",
            lambda: sync_actions.run_copies(
                self._session_factory,
                self._redis,
                self._platforms,
                now=self._clock(),
            ),
        )

    async def _sweep_one(
        self,
        name: str,
        run: Callable[[], Awaitable[object]],
    ) -> None:
        try:
            await run()
        except Exception as error:
            logger.exception(
                "[Worker] Sweep Failed",
                exc_info=error,
                sweep=name,
            )

    def _listening(self) -> bool:
        worker = settings.worker

        return time.monotonic() - self._listened_at < worker.wait_seconds * 3

    async def _beat(self, stop: asyncio.Event) -> None:
        worker = settings.worker
        while not stop.is_set():
            if self._listening():
                try:
                    await sync_actions.beat(
                        self._redis,
                        seconds=worker.heartbeat_seconds * 3,
                    )
                except RedisError:
                    logger.warning("[Worker] Heartbeat Failed - Redis Is Unavailable")
                if worker.health_file is not None:
                    try:
                        worker.health_file.touch()
                    except OSError as error:
                        logger.warning(
                            "[Worker] Health File Not Touched",
                            path=str(worker.health_file),
                            error=repr(error),
                        )
            await _wait(stop, worker.heartbeat_seconds)

    async def _sweep_pushes(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            with monitor_job(WORKER, 60):
                await self.sweep_pushes()
            await _wait(stop, settings.worker.sweep_seconds)

    async def _sweep_imports(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await self.sweep_imports()
            await _wait(stop, settings.worker.sweep_seconds)

    async def _sweep_copies(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await self.sweep_copies()
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

            self._listened_at = time.monotonic()
            if nudge is not None:
                self.take(*nudge)

    async def run(self, stop: asyncio.Event) -> None:
        logger.info(
            "[Worker] Started",
            concurrency=settings.worker.concurrency,
            push_concurrency=settings.worker.push_concurrency,
            sweep_seconds=settings.worker.sweep_seconds,
        )
        self._listened_at = time.monotonic()
        loops = [
            asyncio.create_task(_logged(loop(stop), loop.__name__))
            for loop in (
                self._beat,
                self._sweep_pushes,
                self._sweep_imports,
                self._sweep_copies,
                self._listen,
            )
        ]
        await stop.wait()

        for loop in loops:
            loop.cancel()
        await asyncio.gather(*loops, return_exceptions=True)
        with contextlib.suppress(RedisError):
            await sync_actions.stop_beating(self._redis)

        running = list(self._running.values())
        if running:
            _, unfinished = await asyncio.wait(
                running,
                timeout=settings.worker.stop_seconds,
            )
            for task in unfinished:
                task.cancel()
            await asyncio.gather(*running, return_exceptions=True)

        logger.info("[Worker] Stopped")


async def _logged(loop: Awaitable[None], name: str) -> None:
    try:
        await loop
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.exception(
            "[Worker] Loop Died",
            exc_info=error,
            loop=name,
        )
        raise


async def _wait(stop: asyncio.Event, seconds: float) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=seconds)
