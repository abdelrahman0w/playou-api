from collections.abc import Collection
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement
from sqlalchemy import delete
from sqlalchemy import exists
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.structs import tables
from src.structs.enums import Platforms


def _not_playable_elsewhere(linked: Collection[Platforms]) -> ColumnElement[bool]:
    source = tables.TrackSource

    return ~exists().where(
        source.track_id == tables.Like.track_id,
        source.platform.in_(list(linked)),
    )


async def leftovers(
    session: AsyncSession,
    user_id: UUID,
    linked: Collection[Platforms],
) -> dict[Platforms, tuple[int, int]]:
    like = tables.Like
    playlist = tables.Playlist
    likes = await session.execute(
        select(like.imported_from, func.count())
        .where(
            like.user_id == user_id,
            like.imported_from.is_not(None),
            like.imported_from.not_in(list(linked)),
            _not_playable_elsewhere(linked),
        )
        .group_by(like.imported_from),
    )
    playlists = await session.execute(
        select(playlist.imported_from, func.count())
        .where(
            playlist.user_id == user_id,
            playlist.imported_from.is_not(None),
            playlist.imported_from.not_in(list(linked)),
        )
        .group_by(playlist.imported_from),
    )

    found: dict[Platforms, tuple[int, int]] = {}
    for platform, count in likes:
        if platform is not None:
            found[platform] = (count, 0)
    for platform, count in playlists:
        if platform is not None:
            found[platform] = (found.get(platform, (0, 0))[0], count)

    return found


async def _deleted(session: AsyncSession, statement: Any) -> int:
    result: CursorResult[Any] = await session.execute(statement)  # type: ignore[assignment]

    return result.rowcount


async def delete_platform_data(
    session: AsyncSession,
    user_id: UUID,
    platform: Platforms,
    linked: Collection[Platforms],
) -> tuple[int, int]:
    like = tables.Like
    playlist = tables.Playlist
    likes = await _deleted(
        session,
        delete(like).where(
            like.user_id == user_id,
            like.imported_from == platform,
            _not_playable_elsewhere(linked),
        ),
    )
    playlists = await _deleted(
        session,
        delete(playlist).where(
            playlist.user_id == user_id,
            playlist.imported_from == platform,
        ),
    )
    await session.execute(
        delete(tables.PlaylistLink).where(
            tables.PlaylistLink.user_id == user_id,
            tables.PlaylistLink.platform == platform,
        ),
    )
    await session.execute(
        delete(tables.SyncOperation).where(
            tables.SyncOperation.user_id == user_id,
            tables.SyncOperation.platform == platform,
        ),
    )

    return likes, playlists


async def delete_library(session: AsyncSession, user_id: UUID) -> None:
    for table in (tables.Like, tables.Playlist, tables.SyncOperation):
        await session.execute(delete(table).where(table.user_id == user_id))
