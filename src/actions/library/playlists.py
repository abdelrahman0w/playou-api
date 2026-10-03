from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.actions.sync import enqueue_push
from src.exceptions import NotFoundError
from src.repositories import catalog as catalog_repositories
from src.repositories import library as library_repositories
from src.services import OAuthPlatform
from src.structs.enums import Platforms
from src.structs.enums import RemovedBy
from src.structs.enums import SyncSubjects
from src.structs.models.responses import PlaylistDetail


async def _active_playlist(
    session: AsyncSession,
    user_id: UUID,
    playlist_id: UUID,
) -> PlaylistDetail:
    playlist = await library_repositories.get_playlist(
        session,
        user_id,
        playlist_id,
    )
    if playlist is None or playlist.removed_at is not None:
        raise NotFoundError("The playlist does not exist")

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
    await _active_playlist(session, user_id, playlist_id)
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


async def add_playlist_items(
    session: AsyncSession,
    platforms: dict[Platforms, OAuthPlatform],
    *,
    user_id: UUID,
    playlist_id: UUID,
    track_ids: list[UUID],
    now: datetime,
) -> PlaylistDetail:
    await _active_playlist(session, user_id, playlist_id)

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
    await _active_playlist(session, user_id, playlist_id)

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
