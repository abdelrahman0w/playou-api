import asyncio
from collections.abc import Awaitable
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.actions import accounts as accounts_actions
from src.exceptions import PlatformError
from src.exceptions import PlatformNotFoundError
from src.exceptions import PlatformNotLinkedError
from src.exceptions import PlatformRateLimitedError
from src.exceptions import PlatformReconnectRequiredError
from src.exceptions import QuotaExhaustedError
from src.providers import logger
from src.repositories import accounts as accounts_repositories
from src.repositories import library as library_repositories
from src.repositories import sync as sync_repositories
from src.services import OAuthPlatform
from src.services.limits import charged_to
from src.settings import settings
from src.structs.enums import Platforms
from src.structs.enums import PlaylistKinds
from src.structs.enums import RemovedBy
from src.structs.enums import SyncOutcomes
from src.structs.enums import SyncSubjects
from src.structs.models import LikeSyncState
from src.structs.models import PlatformPlaylist
from src.structs.models import PlaylistSyncState
from src.structs.models import StoredAccount
from src.structs.models import SyncTask


@dataclass(frozen=True)
class _Outcome:
    outcome: SyncOutcomes
    reason: str | None = None


DONE = _Outcome(SyncOutcomes.DONE)

LIKES_A_PUSH = 40
PRUNE_BATCH = 5_000
PUSHED = (SyncSubjects.LIKE, SyncSubjects.PLAYLIST)


def _retry_delay(attempts: int) -> timedelta:
    sync = settings.sync
    seconds = min(
        sync.retry_seconds * 2**attempts,
        sync.longest_retry_seconds,
    )

    return timedelta(seconds=seconds)


Apply = Callable[[AsyncSession], Awaitable[None]]


async def _nothing(_: AsyncSession) -> None:
    return None


@dataclass(frozen=True)
class _Pushed:
    outcomes: list[_Outcome]
    apply: Apply = _nothing


@dataclass(frozen=True)
class _Prepared:
    platform: OAuthPlatform
    account: StoredAccount
    likes: dict[UUID, LikeSyncState] = field(default_factory=dict)
    playlist: PlaylistSyncState | None = None


async def _push_likes(
    platform: OAuthPlatform,
    token: str,
    tasks: list[SyncTask],
    states: dict[UUID, LikeSyncState],
) -> _Pushed:
    outcomes: list[_Outcome] = []
    saves: list[str] = []
    unsaves: list[str] = []
    for task in tasks:
        state = states.get(task.subject_id)
        if state is None:
            outcomes.append(_Outcome(SyncOutcomes.SKIPPED, "The like is gone"))
        elif state.platform_id is None:
            outcomes.append(
                _Outcome(SyncOutcomes.SKIPPED, "The platform does not have the track"),
            )
        else:
            (saves if state.liked else unsaves).append(state.platform_id)
            outcomes.append(DONE)

    if saves:
        await platform.save_tracks(token, saves)
    if unsaves:
        await platform.unsave_tracks(token, unsaves)

    return _Pushed(outcomes)


async def _remember_link(
    session_factory: async_sessionmaker[AsyncSession],
    task: SyncTask,
    remote: PlatformPlaylist,
) -> None:
    async with session_factory() as session, session.begin():
        await library_repositories.save_link(
            session,
            task.subject_id,
            task.platform,
            remote,
        )


def _linking(
    task: SyncTask,
    remote: PlatformPlaylist | None,
) -> Apply:
    async def apply(session: AsyncSession) -> None:
        await library_repositories.save_link(
            session,
            task.subject_id,
            task.platform,
            remote,
        )

    return apply


async def _push_playlist(
    session_factory: async_sessionmaker[AsyncSession],
    platform: OAuthPlatform,
    token: str,
    task: SyncTask,
    state: PlaylistSyncState | None,
    *,
    now: datetime,
) -> _Pushed:
    if state is None:
        return _Pushed([_Outcome(SyncOutcomes.SKIPPED, "The playlist is gone")])
    if state.skipped:
        return _Pushed([_Outcome(SyncOutcomes.SKIPPED, "The playlist is not imported")])
    if state.kind is PlaylistKinds.FOLLOWED and not state.removed:
        return _Pushed(
            [_Outcome(SyncOutcomes.SKIPPED, "A followed playlist is not pushed")],
        )

    remote = state.link
    if state.removed:
        if remote is None:
            return _Pushed([DONE])

        try:
            await platform.delete_playlist(token, remote.platform_id)
        except PlatformNotFoundError:
            pass

        return _Pushed([DONE], _linking(task, None))

    if remote is None:
        remote = await platform.create_playlist(
            token,
            name=state.name,
            description=state.description,
        )
        await _remember_link(session_factory, task, remote)
        remote_ids: list[str] = []
    else:
        try:
            await platform.update_playlist(
                token,
                remote.platform_id,
                name=state.name,
                description=state.description,
            )
            remote_ids = await platform.playlist_track_ids(token, remote.platform_id)
        except PlatformNotFoundError:

            async def gone(session: AsyncSession) -> None:
                await library_repositories.remove_playlist(
                    session,
                    task.subject_id,
                    now=now,
                    removed_by=RemovedBy.PLATFORM,
                )
                await _linking(task, None)(session)

            return _Pushed(
                [_Outcome(SyncOutcomes.DONE, "The platform deleted the playlist")],
                gone,
            )

    there = set(remote_ids)
    to_remove = [pid for pid in state.removed_platform_ids if pid in there]
    to_add = [pid for pid in dict.fromkeys(state.platform_ids) if pid not in there]

    snapshot = remote.snapshot_id
    if to_remove:
        snapshot = (
            await platform.remove_from_playlist(token, remote.platform_id, to_remove)
            or snapshot
        )
    if to_add:
        snapshot = (
            await platform.add_to_playlist(token, remote.platform_id, to_add)
            or snapshot
        )

    return _Pushed(
        [DONE],
        _linking(
            task,
            PlatformPlaylist(platform_id=remote.platform_id, snapshot_id=snapshot),
        ),
    )


async def _prepare(
    session: AsyncSession,
    platforms: dict[Platforms, OAuthPlatform],
    tasks: list[SyncTask],
) -> _Prepared | _Pushed:
    first = tasks[0]

    def every(outcome: _Outcome) -> _Pushed:
        return _Pushed([outcome] * len(tasks))

    platform = platforms.get(first.platform)
    if platform is None:
        return every(_Outcome(SyncOutcomes.SKIPPED, "The platform is not configured"))

    account = await accounts_repositories.get_account(
        session,
        first.user_id,
        first.platform,
    )
    if account is None:
        return every(_Outcome(SyncOutcomes.SKIPPED, "The platform is not linked"))

    wanted = (
        account.push_likes
        if first.subject is SyncSubjects.LIKE
        else account.push_playlists
    )
    if not wanted:
        return every(_Outcome(SyncOutcomes.SKIPPED, "Pushing it was turned off"))

    if first.subject is SyncSubjects.LIKE:
        return _Prepared(
            platform,
            account,
            likes=await library_repositories.like_sync_states(
                session,
                first.user_id,
                [task.subject_id for task in tasks],
                first.platform,
            ),
        )

    return _Prepared(
        platform,
        account,
        playlist=await library_repositories.playlist_sync_state(
            session,
            first.subject_id,
            first.platform,
        ),
    )


async def _push(
    session_factory: async_sessionmaker[AsyncSession],
    prepared: _Prepared | _Pushed,
    tasks: list[SyncTask],
    *,
    now: datetime,
) -> _Pushed:
    if isinstance(prepared, _Pushed):
        return prepared

    platform = prepared.platform

    async def dispatch(token: str) -> _Pushed:
        if tasks[0].subject is SyncSubjects.LIKE:
            return await _push_likes(platform, token, tasks, prepared.likes)

        return await _push_playlist(
            session_factory,
            platform,
            token,
            tasks[0],
            prepared.playlist,
            now=now,
        )

    with charged_to(prepared.account.id):
        return await accounts_actions.with_token(
            session_factory,
            platform,
            prepared.account,
            dispatch,
            now=now,
        )


async def fail_attempt(
    session: AsyncSession,
    task: SyncTask,
    message: str,
    *,
    now: datetime,
) -> SyncOutcomes | None:
    sync = settings.sync
    if task.attempts + 1 >= sync.max_attempts:
        if not await sync_repositories.finish(
            session,
            task.id,
            SyncOutcomes.FAILED,
            now=now,
            error=message,
            requests=task.requests,
        ):
            return None

        logger.warning(
            "[Sync] Push Failed - Out Of Attempts",
            operation_id=task.id,
            platform=task.platform,
            subject=task.subject,
            error=message,
        )

        return SyncOutcomes.FAILED

    await sync_repositories.retry_later(
        session,
        task.id,
        at=now + _retry_delay(task.attempts),
        error=message,
        count_attempt=True,
    )

    return None


async def _settle(
    session: AsyncSession,
    tasks: list[SyncTask],
    pushed: _Pushed | Exception,
    *,
    now: datetime,
) -> list[SyncOutcomes | None]:
    match pushed:
        case PlatformReconnectRequiredError() | PlatformNotLinkedError():
            for task in tasks:
                await sync_repositories.retry_later(
                    session,
                    task.id,
                    at=now + timedelta(seconds=settings.sync.reconnect_retry_seconds),
                    error="The account has to be linked again",
                    count_attempt=False,
                )

            return [None] * len(tasks)
        case PlatformRateLimitedError():
            for task in tasks:
                await sync_repositories.retry_later(
                    session,
                    task.id,
                    at=now + timedelta(seconds=pushed.retry_after_seconds),
                    error=pushed.message,
                    count_attempt=False,
                )

            return [None] * len(tasks)
        case QuotaExhaustedError():
            for task in tasks:
                await sync_repositories.retry_later(
                    session,
                    task.id,
                    at=pushed.retry_at,
                    error=pushed.message,
                    count_attempt=False,
                )

            return [None] * len(tasks)
        case Exception():
            message = (
                pushed.message if isinstance(pushed, PlatformError) else repr(pushed)
            )
            if not isinstance(pushed, PlatformError):
                logger.exception(
                    "[Sync] Push Crashed",
                    exc_info=pushed,
                    operation_ids=[task.id for task in tasks],
                )

            return [
                await fail_attempt(session, task, message, now=now) for task in tasks
            ]

    await pushed.apply(session)
    settled: list[SyncOutcomes | None] = []
    for task, outcome in zip(tasks, pushed.outcomes, strict=True):
        finished = await sync_repositories.finish(
            session,
            task.id,
            outcome.outcome,
            now=now,
            error=outcome.reason if outcome.outcome is SyncOutcomes.SKIPPED else None,
            requests=task.requests,
        )
        settled.append(outcome.outcome if finished else None)

    return settled


async def _keep_leased(
    session_factory: async_sessionmaker[AsyncSession],
    tasks: list[SyncTask],
) -> None:
    seconds = settings.sync.lease_seconds
    while True:
        await asyncio.sleep(seconds / 3)
        try:
            async with session_factory() as session, session.begin():
                await sync_repositories.lease(
                    session,
                    [task.id for task in tasks],
                    seconds=seconds,
                )
        except Exception as error:
            logger.warning(
                "[Sync] Lease Renewal Failed",
                operation_ids=[task.id for task in tasks],
                error=repr(error),
            )


async def _claim(
    session: AsyncSession,
    *,
    now: datetime,
    user_id: UUID | None,
) -> list[SyncTask]:
    task = await sync_repositories.claim_next(
        session,
        now=now,
        subjects=PUSHED,
        user_id=user_id,
    )
    if task is None:
        return []

    tasks = [task]
    if task.subject is SyncSubjects.LIKE:
        tasks += await sync_repositories.claim_alike(
            session,
            task,
            now=now,
            limit=LIKES_A_PUSH - 1,
        )
    await sync_repositories.lease(
        session,
        [task.id for task in tasks],
        seconds=settings.sync.lease_seconds,
    )

    return tasks


async def push_pending(
    session_factory: async_sessionmaker[AsyncSession],
    platforms: dict[Platforms, OAuthPlatform],
    *,
    now: datetime,
    user_id: UUID | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    counts = {"pending": 0} | {outcome.lower(): 0 for outcome in SyncOutcomes}

    pushed = 0
    while pushed < (limit or settings.sync.push_batch_size):
        async with session_factory() as session, session.begin():
            tasks = await _claim(session, now=now, user_id=user_id)
            if not tasks:
                break

            prepared = await _prepare(session, platforms, tasks)

        result: _Pushed | Exception
        renewing = asyncio.create_task(_keep_leased(session_factory, tasks))
        try:
            result = await _push(session_factory, prepared, tasks, now=now)
        except Exception as error:
            result = error
        except asyncio.CancelledError:
            async with session_factory() as session, session.begin():
                await sync_repositories.release(session, [task.id for task in tasks])
            raise
        finally:
            renewing.cancel()
            await asyncio.wait([renewing])

        async with session_factory() as session, session.begin():
            outcomes = await _settle(session, tasks, result, now=now)

        pushed += len(tasks)
        for outcome in outcomes:
            counts[outcome.lower() if outcome is not None else "pending"] += 1

    if any(counts.values()):
        logger.info(
            "[Sync] Pushed",
            **counts,
        )

    return counts


async def prune_finished(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime,
) -> int:
    before = now - timedelta(days=settings.sync.retention_days)
    pruned = 0
    while True:
        async with session_factory() as session, session.begin():
            deleted = await sync_repositories.prune_finished(
                session,
                before=before,
                limit=PRUNE_BATCH,
            )

        pruned += deleted
        if deleted < PRUNE_BATCH:
            break

    logger.info(
        "[Sync] Pruned",
        operations=pruned,
    )

    return pruned
