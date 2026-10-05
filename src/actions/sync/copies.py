import math
from datetime import datetime
from datetime import timedelta
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.actions.catalog.finding import attach
from src.actions.catalog.finding import candidates
from src.actions.catalog.finding import chosen_candidate
from src.actions.catalog.finding import find_match
from src.exceptions import NotFoundError
from src.exceptions import PlatformError
from src.exceptions import PlatformNotLinkedError
from src.exceptions import PlatformRateLimitedError
from src.exceptions import PlatformReconnectRequiredError
from src.exceptions import QuotaExhaustedError
from src.exceptions import UnsupportedError
from src.providers import logger
from src.repositories import accounts as accounts_repositories
from src.repositories import catalog as catalog_repositories
from src.repositories import library as library_repositories
from src.repositories import sync as sync_repositories
from src.services import OAuthPlatform
from src.services.limits import FINDS
from src.services.limits import charged_to
from src.settings import settings
from src.structs import tables
from src.structs.enums import AccountStatuses
from src.structs.enums import CacheKeys
from src.structs.enums import CopyItemStatuses
from src.structs.enums import CopyScopes
from src.structs.enums import CopyStatuses
from src.structs.enums import Platforms
from src.structs.enums import PlaylistKinds
from src.structs.enums import SyncSubjects
from src.structs.models import StoredAccount
from src.structs.models.responses import Candidate
from src.structs.models.responses import CatalogTrack
from src.structs.models.responses import CopyEstimate
from src.structs.models.responses import CopyProgress
from src.structs.models.responses import MissingTracks


COPIES_A_RUN = 10
LOCK_SECONDS = 10 * 60
WITH_LIKES = {CopyScopes.LIKES, CopyScopes.LIBRARY}
LATER = timedelta(minutes=5)
RECONNECT_LATER = timedelta(hours=1)


async def _target(
    session: AsyncSession,
    platforms: dict[Platforms, OAuthPlatform],
    user_id: UUID,
    platform: Platforms,
) -> tuple[OAuthPlatform, StoredAccount]:
    service = platforms.get(platform)
    if service is None or not service.capabilities.copy_to:
        raise UnsupportedError(f"Copying to {platform.title()} is not ready yet")

    account = await accounts_repositories.get_account(session, user_id, platform)
    if account is None:
        raise PlatformNotLinkedError(f"{platform.title()} is not linked")

    return service, account


async def _scope(
    session: AsyncSession,
    platforms: dict[Platforms, OAuthPlatform],
    user_id: UUID,
    platform: Platforms,
    scope: CopyScopes,
    playlist_id: UUID | None,
) -> tuple[OAuthPlatform, CopyScopes, UUID | None]:
    service, _ = await _target(session, platforms, user_id, platform)
    if scope in WITH_LIKES and not service.capabilities.copy_likes:
        if scope is CopyScopes.LIKES:
            raise UnsupportedError(
                f"Copying liked songs to {platform.title()} is turned off",
            )
        scope = CopyScopes.PLAYLISTS
    if scope is not CopyScopes.PLAYLIST:
        return service, scope, None

    playlist = (
        await library_repositories.get_playlist_summary(session, user_id, playlist_id)
        if playlist_id is not None
        else None
    )
    if playlist is None or playlist.removed_at is not None:
        raise NotFoundError("The playlist does not exist")
    if playlist.kind is PlaylistKinds.FOLLOWED:
        raise UnsupportedError("A followed playlist cannot be copied")

    return service, scope, playlist_id


async def estimate_copy(
    session: AsyncSession,
    platforms: dict[Platforms, OAuthPlatform],
    *,
    user_id: UUID,
    platform: Platforms,
    scope: CopyScopes,
    playlist_id: UUID | None,
) -> CopyEstimate:
    service, scope, playlist_id = await _scope(
        session,
        platforms,
        user_id,
        platform,
        scope,
        playlist_id,
    )
    tracks = await sync_repositories.scope_tracks(session, user_id, scope, playlist_id)
    missing = await sync_repositories.tracks_without(session, tracks, platform)
    capabilities = service.capabilities
    days = max(
        _days(len(missing) * capabilities.find_cost, capabilities.daily_find_units),
        _days(len(tracks) * capabilities.write_cost, capabilities.daily_write_units),
    )

    return CopyEstimate(
        scope=scope,
        songs=len(tracks),
        to_find=len(missing),
        days=days,
    )


def _days(units: int, daily: int | None) -> int:
    if not units or not daily:
        return 0

    return math.ceil(units / daily)


async def _progress(
    session: AsyncSession,
    user_id: UUID,
    copy_id: UUID,
) -> CopyProgress:
    for copy in await sync_repositories.list_copies(session, user_id):
        if copy.id == copy_id:
            return copy

    raise NotFoundError("The copy does not exist")


async def start_copy(
    session: AsyncSession,
    platforms: dict[Platforms, OAuthPlatform],
    *,
    user_id: UUID,
    platform: Platforms,
    scope: CopyScopes,
    playlist_id: UUID | None,
) -> CopyProgress:
    _, scope, playlist_id = await _scope(
        session,
        platforms,
        user_id,
        platform,
        scope,
        playlist_id,
    )

    running = await sync_repositories.running_copy(
        session,
        user_id,
        platform,
        scope,
        playlist_id,
    )
    if running is not None:
        return await _progress(session, user_id, running)

    await accounts_repositories.set_push_preferences(
        session,
        user_id,
        platform,
        push_likes=True if scope in WITH_LIKES else None,
        push_playlists=True if scope is not CopyScopes.LIKES else None,
    )
    tracks = await sync_repositories.scope_tracks(session, user_id, scope, playlist_id)
    copy_id = await sync_repositories.create_copy(
        session,
        user_id,
        platform,
        scope,
        playlist_id,
        total=len(tracks),
        missing=await sync_repositories.tracks_without(session, tracks, platform),
    )

    return await _progress(session, user_id, copy_id)


async def cancel_copy(
    session: AsyncSession,
    *,
    user_id: UUID,
    copy_id: UUID,
    now: datetime,
) -> None:
    if not await sync_repositories.end_copy(
        session,
        copy_id,
        CopyStatuses.CANCELED,
        now=now,
        user_id=user_id,
    ):
        raise NotFoundError("The copy is not running")


async def list_copies(session: AsyncSession, *, user_id: UUID) -> list[CopyProgress]:
    return await sync_repositories.list_copies(session, user_id)


async def copy_missing(
    session: AsyncSession,
    *,
    user_id: UUID,
    copy_id: UUID,
) -> list[CatalogTrack]:
    track_ids = await sync_repositories.copy_missing(session, user_id, copy_id)
    if track_ids is None:
        raise NotFoundError("The copy does not exist")

    tracks = await catalog_repositories.get_tracks(session, track_ids)

    return [tracks[track_id] for track_id in track_ids if track_id in tracks]


async def dismiss_copy(
    session: AsyncSession,
    *,
    user_id: UUID,
    copy_id: UUID,
    now: datetime,
) -> None:
    if not await sync_repositories.dismiss_copy(session, user_id, copy_id, now=now):
        raise NotFoundError("The copy does not exist")


async def list_missing(session: AsyncSession, *, user_id: UUID) -> list[MissingTracks]:
    missing = await sync_repositories.missing_tracks(session, user_id)
    tracks = await catalog_repositories.get_tracks(
        session,
        [track_id for track_ids in missing.values() for track_id in track_ids],
    )

    return [
        MissingTracks(
            platform=platform,
            tracks=[tracks[track_id] for track_id in track_ids if track_id in tracks],
        )
        for platform, track_ids in missing.items()
    ]


async def _send(
    session: AsyncSession,
    copy: tables.Copy,
    *,
    now: datetime,
) -> None:
    account = await accounts_repositories.get_account(
        session,
        copy.user_id,
        copy.platform,
    )
    since = account.synced_at if copy.auto and account is not None else None
    likes = (
        await sync_repositories.likes_to_send(
            session,
            copy.user_id,
            copy.platform,
            since=since,
        )
        if copy.scope in WITH_LIKES
        else []
    )
    playlists = await sync_repositories.playlists_to_send(
        session,
        copy.user_id,
        copy.scope,
        copy.playlist_id,
        since=since,
    )
    for subject, subject_ids in (
        (SyncSubjects.LIKE, likes),
        (SyncSubjects.PLAYLIST, playlists),
    ):
        for subject_id in subject_ids:
            await sync_repositories.enqueue(
                session,
                user_id=copy.user_id,
                platform=copy.platform,
                subject=subject,
                subject_id=subject_id,
                now=now,
            )
    if copy.auto and account is not None:
        await accounts_repositories.mark_synced(session, account.id, at=copy.created_at)


async def keep_in_sync(
    session: AsyncSession,
    platforms: dict[Platforms, OAuthPlatform],
    *,
    user_id: UUID,
    now: datetime,
) -> int:
    started = 0
    for account in await accounts_repositories.list_accounts(session, user_id):
        service = platforms.get(account.platform)
        if (
            not account.keep_in_sync
            or service is None
            or not service.capabilities.copy_to
            or account.status_at(now) is AccountStatuses.NEEDS_RECONNECT
        ):
            continue

        scope = (
            CopyScopes.LIBRARY
            if service.capabilities.copy_likes
            else CopyScopes.PLAYLISTS
        )
        if await sync_repositories.running_copy(
            session,
            user_id,
            account.platform,
            scope,
            None,
        ):
            continue

        tracks = await sync_repositories.scope_tracks(session, user_id, scope, None)
        settled = await sync_repositories.settled_tracks(
            session,
            user_id,
            account.platform,
        )
        missing = [
            track_id
            for track_id in await sync_repositories.tracks_without(
                session,
                tracks,
                account.platform,
            )
            if track_id not in settled
        ]
        since = account.synced_at
        sending = (
            scope in WITH_LIKES
            and await sync_repositories.likes_to_send(
                session,
                user_id,
                account.platform,
                since=since,
            )
        ) or await sync_repositories.playlists_to_send(
            session,
            user_id,
            scope,
            None,
            since=since,
        )
        if not missing and not sending:
            continue

        await sync_repositories.create_copy(
            session,
            user_id,
            account.platform,
            scope,
            None,
            total=len(missing),
            missing=missing,
            auto=True,
        )
        started += 1

    return started


async def _find(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    service: OAuthPlatform,
    account: StoredAccount,
    copy: tables.Copy,
    track_id: UUID,
    *,
    now: datetime,
) -> None:
    async with session_factory() as session:
        track = (await catalog_repositories.get_tracks(session, [track_id])).get(
            track_id,
        )
    if track is None:
        return

    there = any(source.platform == copy.platform for source in track.sources)
    found = (
        None
        if there
        else await find_match(
            session_factory,
            redis,
            service,
            account,
            track,
            now=now,
        )
    )

    async with session_factory() as session, session.begin():
        if found is not None:
            track_id = await attach(session, track, found)
        await sync_repositories.set_item(
            session,
            copy.id,
            track_id,
            CopyItemStatuses.FOUND
            if there or found is not None
            else CopyItemStatuses.MISSING,
        )


async def _run_copy(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    platforms: dict[Platforms, OAuthPlatform],
    copy: tables.Copy,
    *,
    now: datetime,
) -> int:
    async with session_factory() as session:
        try:
            service, account = await _target(
                session,
                platforms,
                copy.user_id,
                copy.platform,
            )
        except UnsupportedError, PlatformNotLinkedError:
            service = None
        pending = await sync_repositories.pending_items(
            session,
            copy.id,
            limit=settings.catalog.copy_batch_size,
        )

    if service is None:
        async with session_factory() as session, session.begin():
            await sync_repositories.end_copy(
                session,
                copy.id,
                CopyStatuses.CANCELED,
                now=now,
            )
        return 0

    until: datetime | None = None
    try:
        with charged_to(account.id, FINDS):
            for track_id in pending:
                await _find(
                    session_factory,
                    redis,
                    service,
                    account,
                    copy,
                    track_id,
                    now=now,
                )
    except QuotaExhaustedError as error:
        until = error.retry_at
    except PlatformRateLimitedError as error:
        until = now + timedelta(seconds=error.retry_after_seconds)
    except PlatformReconnectRequiredError:
        until = now + RECONNECT_LATER
    except PlatformError as error:
        logger.warning(
            "[Copy] Search Failed",
            platform=copy.platform,
            error=error.message,
        )
        until = now + LATER

    async with session_factory() as session, session.begin():
        if until is not None:
            await sync_repositories.pause_copy(session, copy.id, until=until)
        elif not await sync_repositories.pending_items(session, copy.id, limit=1):
            await _send(session, copy, now=now)
            await sync_repositories.end_copy(
                session,
                copy.id,
                CopyStatuses.DONE,
                now=now,
            )

    return len(pending)


async def _lock(redis: Redis, copy_id: UUID) -> bool:
    try:
        return bool(
            await redis.set(
                CacheKeys.COPY_LOCK.format(copy_id=copy_id),
                "1",
                nx=True,
                ex=LOCK_SECONDS,
            ),
        )
    except RedisError:
        return True


async def _unlock(redis: Redis, copy_id: UUID) -> None:
    try:
        await redis.delete(CacheKeys.COPY_LOCK.format(copy_id=copy_id))
    except RedisError:
        pass


async def run_copies(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    platforms: dict[Platforms, OAuthPlatform],
    *,
    now: datetime,
    user_id: UUID | None = None,
    rounds: int = 1,
) -> dict[str, int]:
    ran: set[UUID] = set()
    searched = 0
    for _ in range(rounds):
        async with session_factory() as session:
            copies = await sync_repositories.due_copies(
                session,
                now=now,
                limit=COPIES_A_RUN,
                user_id=user_id,
            )

        found = 0
        for copy in copies:
            if not await _lock(redis, copy.id):
                continue
            try:
                found += await _run_copy(
                    session_factory,
                    redis,
                    platforms,
                    copy,
                    now=now,
                )
            finally:
                await _unlock(redis, copy.id)
            ran.add(copy.id)

        searched += found
        if not found:
            break

    if ran:
        logger.info(
            "[Copy] Ran",
            copies=len(ran),
            searched=searched,
        )

    return {"copies": len(ran), "searched": searched}


async def similar_songs(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    platforms: dict[Platforms, OAuthPlatform],
    *,
    user_id: UUID,
    track_id: UUID,
    platform: Platforms,
    now: datetime,
) -> list[Candidate]:
    async with session_factory() as session:
        service, account = await _target(session, platforms, user_id, platform)
        track = (await catalog_repositories.get_tracks(session, [track_id])).get(
            track_id,
        )
    if track is None:
        raise NotFoundError("The track does not exist")

    with charged_to(account.id, FINDS):
        return await candidates(
            session_factory,
            redis,
            service,
            account,
            track,
            now=now,
        )


async def choose_similar(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    platforms: dict[Platforms, OAuthPlatform],
    *,
    user_id: UUID,
    track_id: UUID,
    platform: Platforms,
    platform_id: str | None,
    now: datetime,
) -> CatalogTrack | None:
    async with session_factory() as session, session.begin():
        _, account = await _target(session, platforms, user_id, platform)
        track = (await catalog_repositories.get_tracks(session, [track_id])).get(
            track_id,
        )
        if track is None:
            raise NotFoundError("The track does not exist")

        if platform_id is None:
            await sync_repositories.settle_track(
                session,
                user_id,
                platform,
                track_id,
                CopyItemStatuses.DISMISSED,
            )
            return None

        found = await chosen_candidate(redis, account, track_id, platform_id)
        kept = await attach(session, track, found)
        await sync_repositories.settle_track(
            session,
            user_id,
            platform,
            kept,
            CopyItemStatuses.FOUND,
        )
        like = await library_repositories.get_like(session, user_id, kept)
        sends = [(SyncSubjects.LIKE, kept)] if like and like.removed_at is None else []
        sends += [
            (SyncSubjects.PLAYLIST, playlist_id)
            for playlist_id in await sync_repositories.playlists_with(
                session,
                user_id,
                kept,
            )
        ]
        for subject, subject_id in sends:
            await sync_repositories.enqueue(
                session,
                user_id=user_id,
                platform=platform,
                subject=subject,
                subject_id=subject_id,
                now=now,
            )

        return (await catalog_repositories.get_tracks(session, [kept]))[kept]
