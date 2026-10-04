from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select
from sqlalchemy import exists
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import Exists

from src.structs import tables
from src.structs.enums import CopyItemStatuses
from src.structs.enums import CopyScopes
from src.structs.enums import CopyStatuses
from src.structs.enums import Platforms
from src.structs.enums import PlaylistKinds
from src.structs.models.responses import CopyProgress


WITH_LIKES = {CopyScopes.LIKES, CopyScopes.LIBRARY}


def _on(platform: Platforms) -> Exists:
    source = tables.TrackSource

    return exists().where(
        source.track_id == tables.Track.id,
        source.platform == platform,
    )


def _owned_playlists(user_id: UUID) -> Select[UUID]:
    playlist = tables.Playlist

    return select(playlist.id).where(
        playlist.user_id == user_id,
        playlist.kind == PlaylistKinds.OWNED,
        playlist.removed_at.is_(None),
    )


async def scope_tracks(
    session: AsyncSession,
    user_id: UUID,
    scope: CopyScopes,
    playlist_id: UUID | None,
) -> list[UUID]:
    like = tables.Like
    item = tables.PlaylistItem
    found: list[UUID] = []
    if scope in WITH_LIKES:
        found += await session.scalars(
            select(like.track_id).where(
                like.user_id == user_id,
                like.removed_at.is_(None),
            ),
        )
    if scope is not CopyScopes.LIKES:
        playlists = (
            [playlist_id]
            if scope is CopyScopes.PLAYLIST
            else _owned_playlists(user_id).scalar_subquery()
        )
        found += await session.scalars(
            select(item.track_id).where(
                item.playlist_id.in_(playlists),
                item.removed_at.is_(None),
            ),
        )

    return list(dict.fromkeys(found))


async def tracks_without(
    session: AsyncSession,
    track_ids: list[UUID],
    platform: Platforms,
) -> list[UUID]:
    if not track_ids:
        return []

    track = tables.Track
    found = set(
        await session.scalars(
            select(track.id).where(track.id.in_(track_ids), ~_on(platform)),
        ),
    )

    return [track_id for track_id in track_ids if track_id in found]


async def running_copy(
    session: AsyncSession,
    user_id: UUID,
    platform: Platforms,
    scope: CopyScopes,
    playlist_id: UUID | None,
) -> UUID | None:
    copy = tables.Copy

    return await session.scalar(
        select(copy.id).where(
            copy.user_id == user_id,
            copy.platform == platform,
            copy.scope == scope,
            copy.playlist_id.is_not_distinct_from(playlist_id),
            copy.status == CopyStatuses.RUNNING,
        ),
    )


async def create_copy(
    session: AsyncSession,
    user_id: UUID,
    platform: Platforms,
    scope: CopyScopes,
    playlist_id: UUID | None,
    *,
    total: int,
    missing: list[UUID],
    auto: bool = False,
) -> UUID:
    copy = tables.Copy(
        user_id=user_id,
        platform=platform,
        scope=scope,
        playlist_id=playlist_id,
        status=CopyStatuses.RUNNING,
        total=total,
        auto=auto,
    )
    session.add(copy)
    await session.flush()
    if missing:
        await session.execute(
            insert(tables.CopyItem).values(
                [
                    {
                        "copy_id": copy.id,
                        "track_id": track_id,
                        "status": CopyItemStatuses.PENDING,
                    }
                    for track_id in missing
                ],
            ),
        )

    return copy.id


async def due_copies(
    session: AsyncSession,
    *,
    now: datetime,
    limit: int,
    user_id: UUID | None = None,
) -> list[tables.Copy]:
    copy = tables.Copy
    mine = [copy.user_id == user_id] if user_id is not None else []

    return list(
        await session.scalars(
            select(copy)
            .where(
                copy.status == CopyStatuses.RUNNING,
                (copy.resume_at.is_(None)) | (copy.resume_at <= now),
                *mine,
            )
            .order_by(copy.created_at)
            .limit(limit),
        ),
    )


async def pending_items(
    session: AsyncSession,
    copy_id: UUID,
    *,
    limit: int,
) -> list[UUID]:
    item = tables.CopyItem

    return list(
        await session.scalars(
            select(item.track_id)
            .where(item.copy_id == copy_id, item.status == CopyItemStatuses.PENDING)
            .order_by(item.id)
            .limit(limit),
        ),
    )


async def set_item(
    session: AsyncSession,
    copy_id: UUID,
    track_id: UUID,
    status: CopyItemStatuses,
) -> None:
    item = tables.CopyItem
    await session.execute(
        update(item)
        .where(item.copy_id == copy_id, item.track_id == track_id)
        .values(status=status),
    )


async def settle_track(
    session: AsyncSession,
    user_id: UUID,
    platform: Platforms,
    track_id: UUID,
    status: CopyItemStatuses,
) -> None:
    item = tables.CopyItem
    copy = tables.Copy
    await session.execute(
        update(item)
        .where(
            item.track_id == track_id,
            item.status.in_([CopyItemStatuses.PENDING, CopyItemStatuses.MISSING]),
            item.copy_id.in_(
                select(copy.id).where(
                    copy.user_id == user_id,
                    copy.platform == platform,
                ),
            ),
        )
        .values(status=status),
    )


async def pause_copy(session: AsyncSession, copy_id: UUID, *, until: datetime) -> None:
    await session.execute(
        update(tables.Copy).where(tables.Copy.id == copy_id).values(resume_at=until),
    )


async def end_copy(
    session: AsyncSession,
    copy_id: UUID,
    status: CopyStatuses,
    *,
    now: datetime,
    user_id: UUID | None = None,
) -> bool:
    copy = tables.Copy
    statement = update(copy).where(
        copy.id == copy_id,
        copy.status == CopyStatuses.RUNNING,
    )
    if user_id is not None:
        statement = statement.where(copy.user_id == user_id)
    result: CursorResult[Any] = await session.execute(  # type: ignore[assignment]
        statement.values(status=status, finished_at=now, resume_at=None),
    )

    return bool(result.rowcount)


async def likes_to_send(
    session: AsyncSession,
    user_id: UUID,
    platform: Platforms,
    *,
    since: datetime | None = None,
) -> list[UUID]:
    like = tables.Like
    source = tables.TrackSource
    recent = (
        [(like.created_at > since) | (like.liked_at > since)]
        if since is not None
        else []
    )

    return list(
        await session.scalars(
            select(like.track_id)
            .where(
                like.user_id == user_id,
                like.removed_at.is_(None),
                like.imported_from.is_distinct_from(platform),
                *recent,
                exists().where(
                    source.track_id == like.track_id,
                    source.platform == platform,
                ),
            )
            .order_by(like.liked_at, like.id),
        ),
    )


async def playlists_to_send(
    session: AsyncSession,
    user_id: UUID,
    scope: CopyScopes,
    playlist_id: UUID | None,
    *,
    since: datetime | None = None,
) -> list[UUID]:
    if scope is CopyScopes.PLAYLIST:
        return [playlist_id] if playlist_id is not None else []
    if scope is CopyScopes.LIKES:
        return []

    owned = _owned_playlists(user_id)
    if since is not None:
        playlist = tables.Playlist
        item = tables.PlaylistItem
        owned = owned.where(
            (playlist.created_at > since)
            | exists().where(
                item.playlist_id == playlist.id,
                (item.created_at > since) | (item.updated_at > since),
            ),
        )

    return list(await session.scalars(owned))


async def settled_tracks(
    session: AsyncSession,
    user_id: UUID,
    platform: Platforms,
) -> set[UUID]:
    item = tables.CopyItem
    copy = tables.Copy

    return set(
        await session.scalars(
            select(item.track_id)
            .join(copy, copy.id == item.copy_id)
            .where(
                copy.user_id == user_id,
                copy.platform == platform,
                item.status.in_(
                    [CopyItemStatuses.MISSING, CopyItemStatuses.DISMISSED],
                ),
            ),
        ),
    )


async def playlists_with(
    session: AsyncSession,
    user_id: UUID,
    track_id: UUID,
) -> list[UUID]:
    item = tables.PlaylistItem

    return list(
        await session.scalars(
            _owned_playlists(user_id).where(
                exists().where(
                    item.playlist_id == tables.Playlist.id,
                    item.track_id == track_id,
                    item.removed_at.is_(None),
                ),
            ),
        ),
    )


async def list_copies(
    session: AsyncSession,
    user_id: UUID,
    *,
    limit: int = 20,
) -> list[CopyProgress]:
    copy = tables.Copy
    item = tables.CopyItem
    playlist = tables.Playlist
    rows = (
        await session.execute(
            select(copy, playlist.name)
            .outerjoin(playlist, playlist.id == copy.playlist_id)
            .where(copy.user_id == user_id)
            .order_by(copy.created_at.desc(), copy.id.desc())
            .limit(limit),
        )
    ).all()
    counts: dict[UUID, dict[CopyItemStatuses, int]] = {}
    if rows:
        source = tables.TrackSource
        for copy_id, status, count in await session.execute(
            select(item.copy_id, item.status, func.count())
            .join(copy, copy.id == item.copy_id)
            .where(
                item.copy_id.in_([row[0].id for row in rows]),
                ~exists().where(
                    source.track_id == item.track_id,
                    source.platform == copy.platform,
                ),
            )
            .group_by(item.copy_id, item.status),
        ):
            counts.setdefault(copy_id, {})[status] = count

    return [
        CopyProgress(
            id=row.id,
            platform=row.platform,
            scope=row.scope,
            playlist_id=row.playlist_id,
            playlist_name=name,
            status=row.status,
            total=row.total,
            pending=counts.get(row.id, {}).get(CopyItemStatuses.PENDING, 0),
            missing=counts.get(row.id, {}).get(CopyItemStatuses.MISSING, 0),
            resume_at=row.resume_at,
            created_at=row.created_at,
            finished_at=row.finished_at,
            dismissed_at=row.dismissed_at,
            auto=row.auto,
        )
        for row, name in rows
        if not (
            row.auto
            and row.status is not CopyStatuses.RUNNING
            and not counts.get(row.id, {}).get(CopyItemStatuses.MISSING)
        )
    ]


async def missing_tracks(
    session: AsyncSession,
    user_id: UUID,
) -> dict[Platforms, list[UUID]]:
    item = tables.CopyItem
    copy = tables.Copy
    source = tables.TrackSource
    rows = await session.execute(
        select(copy.platform, item.track_id)
        .join(copy, copy.id == item.copy_id)
        .where(
            copy.user_id == user_id,
            item.status == CopyItemStatuses.MISSING,
            ~exists().where(
                source.track_id == item.track_id,
                source.platform == copy.platform,
            ),
        )
        .distinct(),
    )
    found: dict[Platforms, list[UUID]] = {}
    for platform, track_id in rows:
        found.setdefault(platform, []).append(track_id)

    return found


async def copy_missing(
    session: AsyncSession,
    user_id: UUID,
    copy_id: UUID,
) -> list[UUID] | None:
    copy = await session.scalar(
        select(tables.Copy).where(
            tables.Copy.id == copy_id,
            tables.Copy.user_id == user_id,
        ),
    )
    if copy is None:
        return None

    item = tables.CopyItem
    source = tables.TrackSource

    return list(
        await session.scalars(
            select(item.track_id)
            .where(
                item.copy_id == copy_id,
                item.status == CopyItemStatuses.MISSING,
                ~exists().where(
                    source.track_id == item.track_id,
                    source.platform == copy.platform,
                ),
            )
            .order_by(item.id),
        ),
    )


async def dismiss_copy(
    session: AsyncSession,
    user_id: UUID,
    copy_id: UUID,
    *,
    now: datetime,
) -> bool:
    copy = tables.Copy
    result: CursorResult[Any] = await session.execute(  # type: ignore[assignment]
        update(copy)
        .where(copy.id == copy_id, copy.user_id == user_id)
        .values(dismissed_at=func.coalesce(copy.dismissed_at, now)),
    )

    return bool(result.rowcount)
