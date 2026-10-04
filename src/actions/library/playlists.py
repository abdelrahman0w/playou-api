from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.actions.sync import enqueue_push
from src.actions.sync import request_imports
from src.exceptions import NotFoundError
from src.exceptions import UnsupportedError
from src.repositories import catalog as catalog_repositories
from src.repositories import library as library_repositories
from src.services import OAuthPlatform
from src.structs.enums import Platforms
from src.structs.enums import PlaylistImports
from src.structs.enums import PlaylistKinds
from src.structs.enums import RemovedBy
from src.structs.enums import SyncSubjects
from src.structs.models.responses import PlaylistDetail


async def _active_playlist(
    session: AsyncSession,
    user_id: UUID,
    playlist_id: UUID,
    *,
    editing: bool = False,
) -> PlaylistDetail:
    playlist = await library_repositories.get_playlist(
        session,
        user_id,
        playlist_id,
    )
    if playlist is None or playlist.removed_at is not None:
        raise NotFoundError("The playlist does not exist")
    if editing and playlist.kind is PlaylistKinds.FOLLOWED:
        raise UnsupportedError("A followed playlist is its owner's to change")

    return playlist


async def _pushed(
    session: AsyncSession,
    platforms: dict[Platforms, OAuthPlatform],
    *,
    user_id: UUID,
    playlist_id: UUID,
    now: datetime,
) -> PlaylistDetail:
    await enqueue_push(
        session,
        platforms,
        user_id=user_id,
        subject=SyncSubjects.PLAYLIST,
        subject_id=playlist_id,
        now=now,
    )

    return await _active_playlist(session, user_id, playlist_id)


async def create_playlist(
    session: AsyncSession,
    platforms: dict[Platforms, OAuthPlatform],
    *,
    user_id: UUID,
    name: str,
    description: str | None,
    now: datetime,
) -> PlaylistDetail:
    playlist_id = await library_repositories.create_playlist(
        session,
        user_id,
        name=name,
        description=description,
    )

    return await _pushed(
        session,
        platforms,
        user_id=user_id,
        playlist_id=playlist_id,
        now=now,
    )


async def update_playlist(
    session: AsyncSession,
    platforms: dict[Platforms, OAuthPlatform],
    *,
    user_id: UUID,
    playlist_id: UUID,
    name: str | None,
    description: str | None,
    now: datetime,
) -> PlaylistDetail:
    await _active_playlist(session, user_id, playlist_id, editing=True)
    await library_repositories.update_playlist(
        session,
        playlist_id,
        name=name,
        description=description,
    )

    return await _pushed(
        session,
        platforms,
        user_id=user_id,
        playlist_id=playlist_id,
        now=now,
    )


async def remove_playlist(
    session: AsyncSession,
    platforms: dict[Platforms, OAuthPlatform],
    *,
    user_id: UUID,
    playlist_id: UUID,
    now: datetime,
) -> None:
    await _active_playlist(session, user_id, playlist_id)
    await library_repositories.remove_playlist(
        session,
        playlist_id,
        now=now,
        removed_by=RemovedBy.USER,
    )
    await enqueue_push(
        session,
        platforms,
        user_id=user_id,
        subject=SyncSubjects.PLAYLIST,
        subject_id=playlist_id,
        now=now,
    )


async def choose_importing(
    session: AsyncSession,
    platforms: dict[Platforms, OAuthPlatform],
    *,
    user_id: UUID,
    playlist_id: UUID,
    importing: PlaylistImports,
    now: datetime,
) -> None:
    playlist = await library_repositories.get_playlist(session, user_id, playlist_id)
    if playlist is None or (
        playlist.removed_at is not None and playlist.removed_by is not RemovedBy.SKIPPED
    ):
        raise NotFoundError("The playlist does not exist")

    platform = playlist.imported_from
    if platform is None or all(link.platform != platform for link in playlist.links):
        raise UnsupportedError("Only a playlist imported from an app can be skipped")

    await library_repositories.set_importing(
        session,
        playlist_id,
        platform,
        importing,
    )
    if importing is PlaylistImports.NEVER:
        await library_repositories.skip_playlist(session, playlist_id, now=now)
    else:
        await request_imports(session, platforms, user_id=user_id, now=now)


async def add_playlist_items(
    session: AsyncSession,
    platforms: dict[Platforms, OAuthPlatform],
    *,
    user_id: UUID,
    playlist_id: UUID,
    track_ids: list[UUID],
    now: datetime,
) -> PlaylistDetail:
    await _active_playlist(session, user_id, playlist_id, editing=True)

    found = await catalog_repositories.get_tracks(session, track_ids)
    if missing := [track_id for track_id in track_ids if track_id not in found]:
        raise NotFoundError(
            f"These tracks do not exist: {', '.join(map(str, missing))}"
        )

    await library_repositories.add_items(session, playlist_id, track_ids, now=now)

    return await _pushed(
        session,
        platforms,
        user_id=user_id,
        playlist_id=playlist_id,
        now=now,
    )


async def remove_playlist_item(
    session: AsyncSession,
    platforms: dict[Platforms, OAuthPlatform],
    *,
    user_id: UUID,
    playlist_id: UUID,
    track_id: UUID,
    now: datetime,
) -> None:
    await _active_playlist(session, user_id, playlist_id, editing=True)

    removed = await library_repositories.remove_item(
        session,
        playlist_id,
        track_id,
        now=now,
        removed_by=RemovedBy.USER,
    )
    if not removed:
        raise NotFoundError("The track is not in the playlist")

    await enqueue_push(
        session,
        platforms,
        user_id=user_id,
        subject=SyncSubjects.PLAYLIST,
        subject_id=playlist_id,
        now=now,
    )
