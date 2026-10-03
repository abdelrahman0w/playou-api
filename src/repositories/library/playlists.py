import math
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.catalog import get_tracks
from src.structs import tables
from src.structs.enums import Platforms
from src.structs.enums import RemovedBy
from src.structs.models import Page
from src.structs.models import PlatformPlaylist
from src.structs.models import PlaylistSyncState
from src.structs.models.responses import Playlist
from src.structs.models.responses import PlaylistDetail
from src.structs.models.responses import PlaylistItem
from src.structs.models.responses import PlaylistLink


async def _links(
    session: AsyncSession,
    playlist_ids: list[UUID],
) -> dict[UUID, list[PlaylistLink]]:
    link = tables.PlaylistLink
    rows = await session.scalars(
        select(link)
        .where(link.playlist_id.in_(playlist_ids))
        .order_by(link.created_at),
    )
    by_playlist: dict[UUID, list[PlaylistLink]] = {}
    for row in rows:
        by_playlist.setdefault(row.playlist_id, []).append(
            PlaylistLink(
                platform=row.platform,
                platform_playlist_id=row.platform_playlist_id,
            ),
        )

    return by_playlist


async def _item_counts(
    session: AsyncSession,
    playlist_ids: list[UUID],
) -> dict[UUID, int]:
    item = tables.PlaylistItem
    rows = await session.execute(
        select(item.playlist_id, func.count())
        .where(item.playlist_id.in_(playlist_ids), item.removed_at.is_(None))
        .group_by(item.playlist_id),
    )

    return {playlist_id: count for playlist_id, count in rows}


def _to_playlist(
    row: tables.Playlist,
    *,
    counts: dict[UUID, int],
    links: dict[UUID, list[PlaylistLink]],
) -> Playlist:
    return Playlist(
        id=row.id,
        name=row.name,
        description=row.description,
        item_count=counts.get(row.id, 0),
        links=links.get(row.id, []),
        created_at=row.created_at,
        updated_at=row.updated_at,
        removed_at=row.removed_at,
        removed_by=row.removed_by,
    )


async def create_playlist(
    session: AsyncSession,
    user_id: UUID,
    *,
    name: str,
    description: str | None,
) -> UUID:
    playlist = tables.Playlist(
        user_id=user_id,
        name=name,
        description=description,
    )
    session.add(playlist)
    await session.flush()

    return playlist.id


async def get_playlist(
    session: AsyncSession,
    user_id: UUID,
    playlist_id: UUID,
    *,
    include_removed: bool = False,
) -> PlaylistDetail | None:
    playlist = tables.Playlist
    item = tables.PlaylistItem
    row = await session.scalar(
        select(playlist).where(
            playlist.id == playlist_id,
            playlist.user_id == user_id,
        ),
    )
    if row is None:
        return None

    where = [item.playlist_id == playlist_id]
    if not include_removed:
        where.append(item.removed_at.is_(None))
    items = list(
        await session.scalars(select(item).where(*where).order_by(item.position))
    )
    tracks = await get_tracks(session, [entry.track_id for entry in items])
    summary = _to_playlist(
        row,
        counts=await _item_counts(session, [row.id]),
        links=await _links(session, [row.id]),
    )

    return PlaylistDetail(
        **summary.model_dump(),
        items=[
            PlaylistItem(
                track=tracks[entry.track_id],
                position=entry.position,
                added_at=entry.added_at,
                removed_at=entry.removed_at,
                removed_by=entry.removed_by,
            )
            for entry in items
        ],
    )


async def list_playlists(
    session: AsyncSession,
    user_id: UUID,
    *,
    page: int,
    page_size: int,
    include_removed: bool,
) -> Page[Playlist]:
    playlist = tables.Playlist
    where = [playlist.user_id == user_id]
    if not include_removed:
        where.append(playlist.removed_at.is_(None))

    total = await session.scalar(
        select(func.count()).select_from(playlist).where(*where),
    )
    rows = list(
        await session.scalars(
            select(playlist)
            .where(*where)
            .order_by(playlist.created_at.desc(), playlist.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size),
        ),
    )
    ids = [row.id for row in rows]
    counts = await _item_counts(session, ids)
    links = await _links(session, ids)

    return Page[Playlist](
        items=[_to_playlist(row, counts=counts, links=links) for row in rows],
        page=page,
        page_size=page_size,
        total_count=total or 0,
        total_pages=math.ceil((total or 0) / page_size),
    )


async def update_playlist(
    session: AsyncSession,
    playlist_id: UUID,
    *,
    name: str | None,
    description: str | None,
) -> None:
    values: dict[str, str] = {}
    if name is not None:
        values["name"] = name
    if description is not None:
        values["description"] = description
    if values:
        await session.execute(
            update(tables.Playlist)
            .where(tables.Playlist.id == playlist_id)
            .values(**values),
        )


async def remove_playlist(
    session: AsyncSession,
    playlist_id: UUID,
    *,
    now: datetime,
    removed_by: RemovedBy,
) -> None:
    playlist = tables.Playlist
    await session.execute(
        update(playlist)
        .where(playlist.id == playlist_id, playlist.removed_at.is_(None))
        .values(removed_at=now, removed_by=removed_by),
    )


async def add_items(
    session: AsyncSession,
    playlist_id: UUID,
    track_ids: list[UUID],
    *,
    now: datetime,
) -> None:
    item = tables.PlaylistItem
    rows = await session.execute(
        select(item.track_id, item.removed_at).where(
            item.playlist_id == playlist_id,
            item.track_id.in_(track_ids),
        ),
    )
    active = {track_id for track_id, removed_at in rows if removed_at is None}
    last = await session.scalar(
        select(func.max(item.position)).where(item.playlist_id == playlist_id),
    )
    position = -1 if last is None else last

    for track_id in dict.fromkeys(track_ids):
        if track_id in active:
            continue

        position += 1
        await session.execute(
            insert(item)
            .values(
                playlist_id=playlist_id,
                track_id=track_id,
                position=position,
                added_at=now,
            )
            .on_conflict_do_update(
                index_elements=["playlist_id", "track_id"],
                set_={
                    "position": position,
                    "added_at": now,
                    "removed_at": None,
                    "removed_by": None,
                    "updated_at": func.now(),
                },
            ),
        )


async def remove_item(
    session: AsyncSession,
    playlist_id: UUID,
    track_id: UUID,
    *,
    now: datetime,
    removed_by: RemovedBy,
) -> bool:
    item = tables.PlaylistItem
    removed = await session.scalar(
        update(item)
        .where(
            item.playlist_id == playlist_id,
            item.track_id == track_id,
            item.removed_at.is_(None),
        )
        .values(removed_at=now, removed_by=removed_by)
        .returning(item.id),
    )

    return removed is not None


async def save_link(
    session: AsyncSession,
    playlist_id: UUID,
    platform: Platforms,
    remote: PlatformPlaylist | None,
) -> None:
    link = tables.PlaylistLink
    if remote is None:
        await session.execute(
            delete(link).where(
                link.playlist_id == playlist_id,
                link.platform == platform,
            ),
        )

        return

    await session.execute(
        insert(link)
        .values(
            playlist_id=playlist_id,
            platform=platform,
            platform_playlist_id=remote.platform_id,
            snapshot_id=remote.snapshot_id,
        )
        .on_conflict_do_update(
            index_elements=["playlist_id", "platform"],
            set_={
                "platform_playlist_id": remote.platform_id,
                "snapshot_id": remote.snapshot_id,
                "updated_at": func.now(),
            },
        ),
    )


async def playlist_sync_state(
    session: AsyncSession,
    playlist_id: UUID,
    platform: Platforms,
) -> PlaylistSyncState | None:
    playlist = tables.Playlist
    item = tables.PlaylistItem
    source = tables.TrackSource
    link = tables.PlaylistLink

    row = await session.scalar(select(playlist).where(playlist.id == playlist_id))
    if row is None:
        return None

    remote = await session.scalar(
        select(link).where(link.playlist_id == playlist_id, link.platform == platform),
    )
    items = await session.execute(
        select(source.platform_id, item.removed_at)
        .select_from(item)
        .join(
            source,
            (source.track_id == item.track_id) & (source.platform == platform),
        )
        .where(item.playlist_id == playlist_id)
        .order_by(item.position),
    )
    platform_ids: list[str] = []
    removed_platform_ids: list[str] = []
    for platform_id, removed_at in items:
        (platform_ids if removed_at is None else removed_platform_ids).append(
            platform_id,
        )

    return PlaylistSyncState(
        name=row.name,
        description=row.description,
        removed=row.removed_at is not None,
        link=PlatformPlaylist(
            platform_id=remote.platform_playlist_id,
            snapshot_id=remote.snapshot_id,
        )
        if remote is not None
        else None,
        platform_ids=platform_ids,
        removed_platform_ids=removed_platform_ids,
    )
