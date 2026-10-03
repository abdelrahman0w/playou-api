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
from src.exceptions import PlatformReconnectRequiredError
from src.providers import logger
from src.repositories import accounts as accounts_repositories
from src.repositories import library as library_repositories
from src.repositories import sync as sync_repositories
from src.services import OAuthPlatform
from src.settings import settings
from src.structs.enums import Platforms
from src.structs.enums import RemovedBy
from src.structs.enums import SyncStatuses
from src.structs.enums import SyncSubjects
from src.structs.models import PlatformPlaylist
from src.structs.models import SyncTask


@dataclass(frozen=True)
class _Outcome:
    status: SyncStatuses
    reason: str | None = None


DONE = _Outcome(SyncStatuses.DONE)


def _retry_delay(attempts: int) -> timedelta:
    sync = settings.sync
    seconds = min(
        sync.retry_seconds * 2**attempts,
        sync.longest_retry_seconds,
    )

    return timedelta(seconds=seconds)


async def _push_like(
    session: AsyncSession,
    platform: OAuthPlatform,
    token: str,
    task: SyncTask,
) -> _Outcome:
    state = await library_repositories.like_sync_state(
        session,
        task.user_id,
        task.subject_id,
        task.platform,
    )
    if state is None:
        return _Outcome(SyncStatuses.SKIPPED, "The like is gone")
    if state.platform_id is None:
        return _Outcome(SyncStatuses.SKIPPED, "The platform does not have the track")

    if state.liked:
        await platform.save_tracks(token, [state.platform_id])
    else:
        await platform.unsave_tracks(token, [state.platform_id])

    return DONE


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
        return _Outcome(SyncStatuses.SKIPPED, "The playlist is gone")

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

            return _Outcome(SyncStatuses.DONE, "The platform deleted the playlist")

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
    task: SyncTask,
    *,
    now: datetime,
) -> _Outcome:
    platform = platforms.get(task.platform)
    if platform is None:
        return _Outcome(SyncStatuses.SKIPPED, "The platform is not configured")

    account = await accounts_repositories.get_account(
        session,
        task.user_id,
        task.platform,
    )
    if account is None:
        return _Outcome(SyncStatuses.SKIPPED, "The platform is not linked")

    wanted = (
        account.push_likes
        if task.subject is SyncSubjects.LIKE
        else account.push_playlists
    )
    if not wanted:
        return _Outcome(SyncStatuses.SKIPPED, "Pushing it was turned off")

    token = await accounts_actions.access_token(
        session_factory,
        platform,
        account,
        now=now,
    )
    if task.subject is SyncSubjects.LIKE:
        return await _push_like(session, platform, token, task)

    return await _push_playlist(
        session,
        session_factory,
        platform,
        token,
        task,
        now=now,
    )


async def _settle(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    platforms: dict[Platforms, OAuthPlatform],
    task: SyncTask,
    *,
    now: datetime,
) -> SyncStatuses:
    sync = settings.sync

    try:
        outcome = await _push(session, session_factory, platforms, task, now=now)
    except PlatformReconnectRequiredError, PlatformNotLinkedError:
        await sync_repositories.retry_later(
            session,
            task.id,
            at=now + timedelta(seconds=sync.reconnect_retry_seconds),
            error="The account has to be linked again",
            count_attempt=False,
        )

        return SyncStatuses.PENDING
    except Exception as error:
        message = error.message if isinstance(error, PlatformError) else repr(error)
        if not isinstance(error, PlatformError):
            logger.exception(
                "[Sync] Push Crashed",
                exc_info=error,
                operation_id=task.id,
            )

        if task.attempts + 1 >= sync.max_attempts:
            await sync_repositories.finish(
                session,
                task.id,
                SyncStatuses.FAILED,
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

            return SyncStatuses.FAILED

        await sync_repositories.retry_later(
            session,
            task.id,
            at=now + _retry_delay(task.attempts),
            error=message,
            count_attempt=True,
        )

        return SyncStatuses.PENDING

    await sync_repositories.finish(
        session,
        task.id,
        outcome.status,
        now=now,
        error=outcome.reason if outcome.status is SyncStatuses.SKIPPED else None,
    )

    return outcome.status


async def push_pending(
    session_factory: async_sessionmaker[AsyncSession],
    platforms: dict[Platforms, OAuthPlatform],
    *,
    now: datetime,
    user_id: UUID | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    counts = {status.lower(): 0 for status in SyncStatuses}

    for _ in range(limit or settings.sync.push_batch_size):
        async with session_factory() as session, session.begin():
            task = await sync_repositories.claim_next(
                session,
                now=now,
                user_id=user_id,
            )
            if task is None:
                break

            status = await _settle(
                session,
                session_factory,
                platforms,
                task,
                now=now,
            )

        counts[status.lower()] += 1

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
