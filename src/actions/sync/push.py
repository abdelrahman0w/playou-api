from dataclasses import dataclass
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
from src.providers import logger
from src.repositories import accounts as accounts_repositories
from src.repositories import library as library_repositories
from src.repositories import sync as sync_repositories
from src.services import OAuthPlatform
from src.settings import settings
from src.structs.enums import Platforms
from src.structs.enums import PlaylistKinds
from src.structs.enums import RemovedBy
from src.structs.enums import SyncOutcomes
from src.structs.enums import SyncSubjects
from src.structs.models import PlatformPlaylist
from src.structs.models import SyncTask


@dataclass(frozen=True)
class _Outcome:
    outcome: SyncOutcomes
    reason: str | None = None


DONE = _Outcome(SyncOutcomes.DONE)

LIKES_A_PUSH = 40
PUSHED = (SyncSubjects.LIKE, SyncSubjects.PLAYLIST)


def _retry_delay(attempts: int) -> timedelta:
    sync = settings.sync
    seconds = min(
        sync.retry_seconds * 2**attempts,
        sync.longest_retry_seconds,
    )

    return timedelta(seconds=seconds)


async def _push_likes(
    session: AsyncSession,
    platform: OAuthPlatform,
    token: str,
    tasks: list[SyncTask],
) -> list[_Outcome]:
    first = tasks[0]
    states = await library_repositories.like_sync_states(
        session,
        first.user_id,
        [task.subject_id for task in tasks],
        first.platform,
    )

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

    return outcomes


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


async def _push_playlist(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    platform: OAuthPlatform,
    token: str,
    task: SyncTask,
    *,
    now: datetime,
) -> _Outcome:
    state = await library_repositories.playlist_sync_state(
        session,
        task.subject_id,
        task.platform,
    )
    if state is None:
        return _Outcome(SyncOutcomes.SKIPPED, "The playlist is gone")
    if state.kind is PlaylistKinds.FOLLOWED and not state.removed:
        return _Outcome(SyncOutcomes.SKIPPED, "A followed playlist is not pushed")

    remote = state.link
    if state.removed:
        if remote is not None:
            try:
                await platform.delete_playlist(token, remote.platform_id)
            except PlatformNotFoundError:
                pass
            await library_repositories.save_link(
                session,
                task.subject_id,
                task.platform,
                None,
            )

        return DONE

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
            await library_repositories.remove_playlist(
                session,
                task.subject_id,
                now=now,
                removed_by=RemovedBy.PLATFORM,
            )
            await library_repositories.save_link(
                session,
                task.subject_id,
                task.platform,
                None,
            )

            return _Outcome(SyncOutcomes.DONE, "The platform deleted the playlist")

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

    await library_repositories.save_link(
        session,
        task.subject_id,
        task.platform,
        PlatformPlaylist(platform_id=remote.platform_id, snapshot_id=snapshot),
    )

    return DONE


async def _push(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    platforms: dict[Platforms, OAuthPlatform],
    tasks: list[SyncTask],
    *,
    now: datetime,
) -> list[_Outcome]:
    first = tasks[0]

    def every(outcome: _Outcome) -> list[_Outcome]:
        return [outcome] * len(tasks)

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

    async def dispatch(token: str) -> list[_Outcome]:
        if first.subject is SyncSubjects.LIKE:
            return await _push_likes(session, platform, token, tasks)

        return [
            await _push_playlist(
                session,
                session_factory,
                platform,
                token,
                first,
                now=now,
            ),
        ]

    return await accounts_actions.with_token(
        session_factory,
        platform,
        account,
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
        await sync_repositories.finish(
            session,
            task.id,
            SyncOutcomes.FAILED,
            now=now,
            error=message,
        )
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
    session_factory: async_sessionmaker[AsyncSession],
    platforms: dict[Platforms, OAuthPlatform],
    tasks: list[SyncTask],
    *,
    now: datetime,
) -> list[SyncOutcomes | None]:
    try:
        outcomes = await _push(session, session_factory, platforms, tasks, now=now)
    except PlatformReconnectRequiredError, PlatformNotLinkedError:
        for task in tasks:
            await sync_repositories.retry_later(
                session,
                task.id,
                at=now + timedelta(seconds=settings.sync.reconnect_retry_seconds),
                error="The account has to be linked again",
                count_attempt=False,
            )

        return [None] * len(tasks)
    except PlatformRateLimitedError as error:
        for task in tasks:
            await sync_repositories.retry_later(
                session,
                task.id,
                at=now + timedelta(seconds=error.retry_after_seconds),
                error=error.message,
                count_attempt=False,
            )

        return [None] * len(tasks)
    except Exception as error:
        message = error.message if isinstance(error, PlatformError) else repr(error)
        if not isinstance(error, PlatformError):
            logger.exception(
                "[Sync] Push Crashed",
                exc_info=error,
                operation_ids=[task.id for task in tasks],
            )

        return [await fail_attempt(session, task, message, now=now) for task in tasks]

    for task, outcome in zip(tasks, outcomes, strict=True):
        await sync_repositories.finish(
            session,
            task.id,
            outcome.outcome,
            now=now,
            error=outcome.reason if outcome.outcome is SyncOutcomes.SKIPPED else None,
        )

    return [outcome.outcome for outcome in outcomes]


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
            task = await sync_repositories.claim_next(
                session,
                now=now,
                subjects=PUSHED,
                user_id=user_id,
            )
            if task is None:
                break

            tasks = [task]
            if task.subject is SyncSubjects.LIKE:
                tasks += await sync_repositories.claim_alike(
                    session,
                    task,
                    now=now,
                    limit=LIKES_A_PUSH - 1,
                )

            outcomes = await _settle(
                session,
                session_factory,
                platforms,
                tasks,
                now=now,
            )

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
    async with session_factory() as session, session.begin():
        pruned = await sync_repositories.prune_finished(session, before=before)

    logger.info(
        "[Sync] Pruned",
        operations=pruned,
    )

    return pruned
