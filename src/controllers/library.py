from datetime import datetime
from datetime import timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.actions import library as library_actions
from src.actions import sync as sync_actions
from src.exceptions import NotFoundError
from src.repositories import library as library_repositories
from src.services import OAuthPlatform
from src.settings import settings
from src.structs.enums import Platforms
from src.structs.models import Page
from src.structs.models.requests import CreatePlaylistRequest
from src.structs.models.requests import LibraryListRequest
from src.structs.models.requests import PlaylistItemsRequest
from src.structs.models.requests import PlaylistListRequest
from src.structs.models.requests import UpdatePlaylistRequest
from src.structs.models.responses import AccountSync
from src.structs.models.responses import LikedTrack
from src.structs.models.responses import PlatformData
from src.structs.models.responses import Playlist
from src.structs.models.responses import PlaylistDetail


async def _refresh_when_stale(
    session: AsyncSession,
    platforms: dict[Platforms, OAuthPlatform],
    *,
    user_id: UUID,
    now: datetime,
) -> None:
    await sync_actions.request_imports(
        session,
        platforms,
        user_id=user_id,
        now=now,
        stale_before=now - timedelta(minutes=settings.imports.stale_minutes),
    )


async def list_likes(
    session: AsyncSession,
    platforms: dict[Platforms, OAuthPlatform],
    request: LibraryListRequest,
    *,
    user_id: UUID,
    now: datetime,
) -> Page[LikedTrack]:
    async with session.begin():
        await _refresh_when_stale(session, platforms, user_id=user_id, now=now)

        return await library_repositories.list_likes(
            session,
            user_id,
            page=request.page,
            page_size=request.page_size,
            include_removed=request.include_removed,
            platform=request.platform,
            query=request.q,
        )


async def like(
    session: AsyncSession,
    platforms: dict[Platforms, OAuthPlatform],
    track_id: UUID,
    *,
    user_id: UUID,
    now: datetime,
) -> LikedTrack:
    async with session.begin():
        return await library_actions.like_track(
            session,
            platforms,
            user_id=user_id,
            track_id=track_id,
            now=now,
        )


async def unlike(
    session: AsyncSession,
    platforms: dict[Platforms, OAuthPlatform],
    track_id: UUID,
    *,
    user_id: UUID,
    now: datetime,
) -> None:
    async with session.begin():
        await library_actions.unlike_track(
            session,
            platforms,
            user_id=user_id,
            track_id=track_id,
            now=now,
        )


async def list_playlists(
    session: AsyncSession,
    platforms: dict[Platforms, OAuthPlatform],
    request: PlaylistListRequest,
    *,
    user_id: UUID,
    now: datetime,
) -> Page[Playlist]:
    async with session.begin():
        await _refresh_when_stale(session, platforms, user_id=user_id, now=now)

        return await library_repositories.list_playlists(
            session,
            user_id,
            page=request.page,
            page_size=request.page_size,
            include_removed=request.include_removed,
            kind=request.kind,
            platform=request.platform,
            query=request.q,
        )


async def request_import(
    session: AsyncSession,
    platforms: dict[Platforms, OAuthPlatform],
    *,
    user_id: UUID,
    now: datetime,
) -> list[AccountSync]:
    async with session.begin():
        await sync_actions.request_imports(
            session,
            platforms,
            user_id=user_id,
            now=now,
            stale_before=now - timedelta(seconds=settings.imports.cooldown_seconds),
        )

        return await sync_actions.library_sync(session, platforms, user_id=user_id)


async def get_sync(
    session: AsyncSession,
    platforms: dict[Platforms, OAuthPlatform],
    *,
    user_id: UUID,
) -> list[AccountSync]:
    async with session.begin():
        return await sync_actions.library_sync(session, platforms, user_id=user_id)


async def get_playlist(
    session: AsyncSession,
    playlist_id: UUID,
    *,
    user_id: UUID,
    include_removed: bool,
) -> PlaylistDetail:
    async with session.begin():
        playlist = await library_repositories.get_playlist(
            session,
            user_id,
            playlist_id,
            include_removed=include_removed,
        )

    if playlist is None:
        raise NotFoundError("The playlist does not exist")

    return playlist


async def create_playlist(
    session: AsyncSession,
    platforms: dict[Platforms, OAuthPlatform],
    request: CreatePlaylistRequest,
    *,
    user_id: UUID,
    now: datetime,
) -> PlaylistDetail:
    async with session.begin():
        return await library_actions.create_playlist(
            session,
            platforms,
            user_id=user_id,
            name=request.name,
            description=request.description,
            now=now,
        )


async def update_playlist(
    session: AsyncSession,
    platforms: dict[Platforms, OAuthPlatform],
    playlist_id: UUID,
    request: UpdatePlaylistRequest,
    *,
    user_id: UUID,
    now: datetime,
) -> PlaylistDetail:
    async with session.begin():
        return await library_actions.update_playlist(
            session,
            platforms,
            user_id=user_id,
            playlist_id=playlist_id,
            name=request.name,
            description=request.description,
            now=now,
        )


async def remove_playlist(
    session: AsyncSession,
    platforms: dict[Platforms, OAuthPlatform],
    playlist_id: UUID,
    *,
    user_id: UUID,
    now: datetime,
) -> None:
    async with session.begin():
        await library_actions.remove_playlist(
            session,
            platforms,
            user_id=user_id,
            playlist_id=playlist_id,
            now=now,
        )


async def add_playlist_items(
    session: AsyncSession,
    platforms: dict[Platforms, OAuthPlatform],
    playlist_id: UUID,
    request: PlaylistItemsRequest,
    *,
    user_id: UUID,
    now: datetime,
) -> PlaylistDetail:
    async with session.begin():
        return await library_actions.add_playlist_items(
            session,
            platforms,
            user_id=user_id,
            playlist_id=playlist_id,
            track_ids=request.track_ids,
            now=now,
        )


async def remove_playlist_item(
    session: AsyncSession,
    platforms: dict[Platforms, OAuthPlatform],
    playlist_id: UUID,
    track_id: UUID,
    *,
    user_id: UUID,
    now: datetime,
) -> None:
    async with session.begin():
        await library_actions.remove_playlist_item(
            session,
            platforms,
            user_id=user_id,
            playlist_id=playlist_id,
            track_id=track_id,
            now=now,
        )


async def import_now(
    session_factory: async_sessionmaker[AsyncSession],
    platforms: dict[Platforms, OAuthPlatform],
    *,
    user_id: UUID,
    now: datetime,
) -> None:
    await sync_actions.import_user(
        session_factory,
        platforms,
        user_id=user_id,
        now=now,
    )


async def push_changes(
    session_factory: async_sessionmaker[AsyncSession],
    platforms: dict[Platforms, OAuthPlatform],
    *,
    user_id: UUID,
    now: datetime,
) -> None:
    await sync_actions.push_pending(
        session_factory,
        platforms,
        now=now,
        user_id=user_id,
    )


async def get_data(
    session: AsyncSession,
    *,
    user_id: UUID,
) -> list[PlatformData]:
    async with session.begin():
        return await library_actions.leftovers(session, user_id)


async def remove_platform_data(
    session: AsyncSession,
    platform: Platforms,
    *,
    user_id: UUID,
) -> None:
    library_actions.ensure_allowed()
    async with session.begin():
        await library_actions.remove_platform_data(session, user_id, platform)


async def clear_library(
    session: AsyncSession,
    *,
    user_id: UUID,
    unlink: bool,
) -> None:
    library_actions.ensure_allowed()
    async with session.begin():
        await library_actions.clear_library(session, user_id, unlink=unlink)
