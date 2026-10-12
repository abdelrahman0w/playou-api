import math
from datetime import datetime
from itertools import batched
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement
from sqlalchemy import case
from sqlalchemy import delete
from sqlalchemy import exists
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.catalog import get_tracks
from src.structs import tables
from src.structs.enums import Platforms
from src.structs.enums import PlaylistImports
from src.structs.enums import PlaylistKinds
from src.structs.enums import PlaylistSorts
from src.structs.enums import RemovedBy
from src.structs.models import LinkedPlaylist
from src.structs.models import Page
from src.structs.models import PlatformPlaylist
from src.structs.models import PlaylistSyncState
from src.structs.models import RemotePlaylist
from src.structs.models.responses import Playlist
from src.structs.models.responses import PlaylistDetail
from src.structs.models.responses import PlaylistItem
from src.structs.models.responses import PlaylistLink
from src.utils.search import matching
from src.utils.sql import ROWS_PER_INSERT
from src.utils.sql import any_of
from src.utils.sql import none_of


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
                importing=row.importing,
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
        kind=row.kind,
        name=row.name,
        description=row.description,
        owner_name=row.owner_name,
        cover_url=row.cover_url,
        url=row.url,
        item_count=counts.get(row.id, 0),
        links=links.get(row.id, []),
        imported_from=row.imported_from,
        on_profile=row.on_profile,
        pinned=row.pinned_at is not None,
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


async def get_playlist_row(
    session: AsyncSession,
    user_id: UUID,
    playlist_id: UUID,
) -> tables.Playlist | None:
    playlist = tables.Playlist

    return await session.scalar(
        select(playlist).where(
            playlist.id == playlist_id,
            playlist.user_id == user_id,
        ),
    )


async def get_playlist_summary(
    session: AsyncSession,
    user_id: UUID,
    playlist_id: UUID,
) -> Playlist | None:
    row = await get_playlist_row(session, user_id, playlist_id)
    if row is None:
        return None

    return _to_playlist(
        row,
        counts=await _item_counts(session, [row.id]),
        links=await _links(session, [row.id]),
    )


async def get_playlist(
    session: AsyncSession,
    user_id: UUID,
    playlist_id: UUID,
    *,
    include_removed: bool = False,
) -> PlaylistDetail | None:
    row = await get_playlist_row(session, user_id, playlist_id)
    if row is None:
        return None

    item = tables.PlaylistItem
    where = [item.playlist_id == playlist_id]
    if not include_removed:
        where.append(item.removed_at.is_(None))
    items = (
        await session.execute(
            select(
                item.track_id,
                item.position,
                item.added_at,
                item.removed_at,
                item.removed_by,
            )
            .where(*where)
            .order_by(item.removed_at.is_not(None), item.position)
        )
    ).all()
    tracks = await get_tracks(session, [entry.track_id for entry in items])
    summary = _to_playlist(
        row,
        counts={row.id: sum(entry.removed_at is None for entry in items)},
        links=await _links(session, [row.id]),
    )

    return PlaylistDetail(
        **dict(summary),
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


def _sorted_by(sort: PlaylistSorts) -> tuple[ColumnElement[Any], ...]:
    playlist = tables.Playlist
    if sort is PlaylistSorts.NAME:
        return func.search_fold(playlist.name), playlist.id.asc()
    if sort is PlaylistSorts.CUSTOM:
        return (
            playlist.library_position.asc().nulls_first(),
            playlist.created_at.desc(),
            playlist.id.desc(),
        )

    return playlist.created_at.desc(), playlist.id.desc()


async def list_playlists(
    session: AsyncSession,
    user_id: UUID,
    *,
    page: int,
    page_size: int,
    include_removed: bool,
    kind: PlaylistKinds | None = None,
    platform: Platforms | None = None,
    query: str | None = None,
    skipped: bool = False,
    sort: PlaylistSorts = PlaylistSorts.RECENT,
) -> Page[Playlist]:
    playlist = tables.Playlist
    where = [playlist.user_id == user_id]
    if skipped:
        where.append(playlist.removed_by == RemovedBy.SKIPPED)
    else:
        where.append(playlist.removed_by.is_distinct_from(RemovedBy.SKIPPED))
    if not include_removed and not skipped:
        where.append(playlist.removed_at.is_(None))
    if kind is not None:
        where.append(playlist.kind == kind)
    if platform is not None:
        link = tables.PlaylistLink
        where.append(
            exists().where(
                link.playlist_id == playlist.id,
                link.platform == platform,
            ),
        )
    if query:
        where.extend(matching(func.search_fold(playlist.name), query))

    total = await session.scalar(
        select(func.count()).select_from(playlist).where(*where),
    )
    rows = list(
        await session.scalars(
            select(playlist)
            .where(*where)
            .order_by(playlist.pinned_at.is_(None), *_sorted_by(sort))
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
            any_of(item.track_id, track_ids),
        ),
    )
    active = {track_id for track_id, removed_at in rows if removed_at is None}
    last = await session.scalar(
        select(func.max(item.position)).where(item.playlist_id == playlist_id),
    )
    start = 0 if last is None else last + 1
    adding = [
        track_id for track_id in dict.fromkeys(track_ids) if track_id not in active
    ]
    if not adding:
        return

    statement = insert(item).values(
        [
            {
                "playlist_id": playlist_id,
                "track_id": track_id,
                "position": start + offset,
                "added_at": now,
            }
            for offset, track_id in enumerate(adding)
        ],
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["playlist_id", "track_id"],
            set_={
                "position": statement.excluded.position,
                "added_at": statement.excluded.added_at,
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
            user_id=select(tables.Playlist.user_id)
            .where(tables.Playlist.id == playlist_id)
            .scalar_subquery(),
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
        kind=row.kind,
        name=row.name,
        description=row.description,
        removed=row.removed_at is not None,
        skipped=row.removed_by is RemovedBy.SKIPPED,
        link=PlatformPlaylist(
            platform_id=remote.platform_playlist_id,
            snapshot_id=remote.snapshot_id,
        )
        if remote is not None
        else None,
        platform_ids=platform_ids,
        removed_platform_ids=removed_platform_ids,
    )


async def platform_links(
    session: AsyncSession,
    user_id: UUID,
    platform: Platforms,
) -> dict[str, LinkedPlaylist]:
    playlist = tables.Playlist
    link = tables.PlaylistLink
    rows = await session.execute(
        select(
            link.platform_playlist_id,
            playlist.id,
            playlist.kind,
            link.snapshot_id,
            playlist.removed_at,
            playlist.removed_by,
            link.importing,
        )
        .join(playlist, playlist.id == link.playlist_id)
        .where(playlist.user_id == user_id, link.platform == platform),
    )

    return {
        row.platform_playlist_id: LinkedPlaylist(
            playlist_id=row.id,
            kind=row.kind,
            snapshot_id=row.snapshot_id,
            removed=row.removed_at is not None,
            skipped=row.removed_by is RemovedBy.SKIPPED,
            importing=row.importing,
        )
        for row in rows
    }


async def import_playlist(
    session: AsyncSession,
    user_id: UUID,
    platform: Platforms,
    remote: RemotePlaylist,
    *,
    kind: PlaylistKinds,
) -> UUID:
    playlist = tables.Playlist(
        user_id=user_id,
        kind=kind,
        name=remote.name[:200] or "Untitled",
        description=remote.description,
        owner_name=remote.owner_name,
        cover_url=remote.cover_url,
        url=remote.url,
        imported_from=platform,
    )
    session.add(playlist)
    await session.flush()
    await save_link(
        session,
        playlist.id,
        platform,
        PlatformPlaylist(platform_id=remote.platform_id),
    )

    return playlist.id


async def update_from_platform(
    session: AsyncSession,
    playlist_id: UUID,
    remote: RemotePlaylist,
    *,
    kind: PlaylistKinds,
) -> None:
    await session.execute(
        update(tables.Playlist)
        .where(tables.Playlist.id == playlist_id)
        .values(
            kind=kind,
            name=remote.name[:200] or "Untitled",
            description=remote.description,
            owner_name=remote.owner_name,
            cover_url=remote.cover_url,
            url=remote.url,
            removed_at=None,
            removed_by=None,
        ),
    )


async def reconcile_items(
    session: AsyncSession,
    playlist_id: UUID,
    track_ids: list[UUID],
    *,
    now: datetime,
) -> None:
    item = tables.PlaylistItem
    ordered = list(dict.fromkeys(track_ids))

    await session.execute(
        update(item)
        .where(
            item.playlist_id == playlist_id,
            item.removed_at.is_(None),
            none_of(item.track_id, ordered),
        )
        .values(removed_at=now, removed_by=RemovedBy.PLATFORM),
    )
    for chunk in batched(enumerate(ordered), ROWS_PER_INSERT, strict=False):
        statement = insert(item).values(
            [
                {
                    "playlist_id": playlist_id,
                    "track_id": track_id,
                    "position": position,
                    "added_at": now,
                }
                for position, track_id in chunk
            ],
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["playlist_id", "track_id"],
                set_={
                    "position": statement.excluded.position,
                    "added_at": case(
                        (item.removed_at.is_(None), item.added_at),
                        else_=statement.excluded.added_at,
                    ),
                    "removed_at": None,
                    "removed_by": None,
                    "updated_at": func.now(),
                },
                where=or_(
                    item.removed_at.is_not(None),
                    item.position != statement.excluded.position,
                ),
            ),
        )


async def remove_playlists(
    session: AsyncSession,
    playlist_ids: list[UUID],
    *,
    now: datetime,
    removed_by: RemovedBy,
) -> None:
    if not playlist_ids:
        return

    playlist = tables.Playlist
    await session.execute(
        update(playlist)
        .where(playlist.id.in_(playlist_ids), playlist.removed_at.is_(None))
        .values(removed_at=now, removed_by=removed_by),
    )


async def skip_playlist(
    session: AsyncSession,
    playlist_id: UUID,
    *,
    now: datetime,
) -> None:
    playlist = tables.Playlist
    await session.execute(
        update(playlist)
        .where(playlist.id == playlist_id)
        .values(
            removed_at=func.coalesce(playlist.removed_at, now),
            removed_by=RemovedBy.SKIPPED,
        ),
    )


async def delete_playlists(session: AsyncSession, playlist_ids: list[UUID]) -> None:
    if playlist_ids:
        await session.execute(
            delete(tables.Playlist).where(tables.Playlist.id.in_(playlist_ids)),
        )


async def set_importing(
    session: AsyncSession,
    playlist_id: UUID,
    platform: Platforms,
    importing: PlaylistImports,
) -> None:
    link = tables.PlaylistLink
    await session.execute(
        update(link)
        .where(link.playlist_id == playlist_id, link.platform == platform)
        .values(importing=importing, snapshot_id=None),
    )


async def set_pinned(
    session: AsyncSession,
    user_id: UUID,
    playlist_id: UUID,
    *,
    pinned_at: datetime | None,
) -> bool:
    playlist = tables.Playlist
    changed = await session.scalar(
        update(playlist)
        .where(
            playlist.id == playlist_id,
            playlist.user_id == user_id,
            playlist.removed_at.is_(None),
        )
        .values(pinned_at=pinned_at)
        .returning(playlist.id),
    )

    return changed is not None


async def set_library_order(
    session: AsyncSession,
    user_id: UUID,
    playlist_ids: list[UUID],
) -> None:
    playlist = tables.Playlist
    positions = {playlist_id: index for index, playlist_id in enumerate(playlist_ids)}
    await session.execute(
        update(playlist)
        .where(playlist.user_id == user_id)
        .values(
            library_position=case(positions, value=playlist.id, else_=None)
            if positions
            else None,
        ),
    )
