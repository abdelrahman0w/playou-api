import math
from collections.abc import Collection
from datetime import datetime
from uuid import UUID

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.catalog import get_tracks
from src.structs import tables
from src.structs.enums import PlaylistKinds
from src.structs.enums import ShareSubjects
from src.structs.models import Page
from src.structs.models.responses import CatalogTrack
from src.structs.models.responses import ReceivedShare
from src.structs.models.responses import SentShare
from src.structs.models.responses import SharedPlaylist
from src.structs.models.responses import ShareOpener
from src.structs.models.responses import Sharer
from src.utils.shares import share_url
from src.utils.sql import any_of


async def create_share(
    session: AsyncSession,
    user_id: UUID,
    *,
    code: str,
    track_id: UUID | None = None,
    playlist_id: UUID | None = None,
) -> UUID | None:
    share = tables.Share

    return await session.scalar(
        insert(share)
        .values(
            code=code,
            user_id=user_id,
            subject=ShareSubjects.TRACK if track_id else ShareSubjects.PLAYLIST,
            track_id=track_id,
            playlist_id=playlist_id,
        )
        .on_conflict_do_nothing(index_elements=["code"])
        .returning(share.id),
    )


async def shareable_playlist(
    session: AsyncSession,
    user_id: UUID,
    playlist_id: UUID,
) -> bool:
    playlist = tables.Playlist

    return (
        await session.scalar(
            select(playlist.id).where(
                playlist.id == playlist_id,
                playlist.user_id == user_id,
                playlist.kind == PlaylistKinds.OWNED,
                playlist.removed_at.is_(None),
            ),
        )
        is not None
    )


async def shared_playlists(
    session: AsyncSession,
    shares: Collection[tables.Share],
) -> dict[UUID, SharedPlaylist]:
    wanted = {share.playlist_id: share for share in shares if share.playlist_id}
    if not wanted:
        return {}

    playlist = tables.Playlist
    item = tables.PlaylistItem
    counted = (
        select(item.playlist_id, func.count().label("songs"))
        .where(any_of(item.playlist_id, wanted), item.removed_at.is_(None))
        .group_by(item.playlist_id)
        .subquery()
    )
    rows = await session.execute(
        select(playlist, func.coalesce(counted.c.songs, 0))
        .outerjoin(counted, counted.c.playlist_id == playlist.id)
        .where(any_of(playlist.id, wanted), playlist.removed_at.is_(None)),
    )
    by_playlist = {row.id: (row, songs) for row, songs in rows}

    return {
        share.id: SharedPlaylist(
            code=share.code,
            name=found[0].name,
            description=found[0].description,
            cover_url=found[0].cover_url,
            item_count=found[1],
        )
        for share in shares
        if share.playlist_id and (found := by_playlist.get(share.playlist_id))
    }


async def playlist_tracks(
    session: AsyncSession,
    playlist_id: UUID,
    *,
    page: int,
    page_size: int,
) -> Page[CatalogTrack]:
    item = tables.PlaylistItem
    where = [item.playlist_id == playlist_id, item.removed_at.is_(None)]
    total = await session.scalar(select(func.count()).select_from(item).where(*where))
    track_ids = list(
        await session.scalars(
            select(item.track_id)
            .where(*where)
            .order_by(item.position, item.id)
            .offset((page - 1) * page_size)
            .limit(page_size),
        ),
    )
    tracks = await get_tracks(session, track_ids)

    return Page[CatalogTrack](
        items=[tracks[track_id] for track_id in track_ids if track_id in tracks],
        page=page,
        page_size=page_size,
        total_count=total or 0,
        total_pages=math.ceil((total or 0) / page_size),
    )


async def get_live_share(session: AsyncSession, code: str) -> tables.Share | None:
    share = tables.Share

    return await session.scalar(
        select(share).where(share.code == code, share.revoked_at.is_(None)),
    )


async def sharer_name(session: AsyncSession, share_id: UUID) -> str:
    user = tables.User
    share = tables.Share
    name = await session.scalar(
        select(user.name)
        .join(share, share.user_id == user.id)
        .where(share.id == share_id),
    )

    return name or ""


async def count_anonymous_open(session: AsyncSession, share_id: UUID) -> None:
    share = tables.Share
    await session.execute(
        update(share)
        .where(share.id == share_id)
        .values(anonymous_opens=share.anonymous_opens + 1),
    )


async def record_open(
    session: AsyncSession,
    share_id: UUID,
    user_id: UUID,
    *,
    now: datetime,
) -> bool:
    opened = tables.ShareOpen
    opens = await session.scalar(
        insert(opened)
        .values(
            share_id=share_id,
            user_id=user_id,
            first_opened_at=now,
            last_opened_at=now,
        )
        .on_conflict_do_update(
            index_elements=["share_id", "user_id"],
            set_={
                "opens": opened.opens + 1,
                "last_opened_at": now,
                "updated_at": func.now(),
            },
        )
        .returning(opened.opens),
    )

    return opens == 1


async def revoke_share(
    session: AsyncSession,
    user_id: UUID,
    code: str,
    *,
    now: datetime,
) -> bool:
    share = tables.Share
    revoked = await session.scalar(
        update(share)
        .where(
            share.code == code,
            share.user_id == user_id,
            share.revoked_at.is_(None),
        )
        .values(revoked_at=now)
        .returning(share.id),
    )

    return revoked is not None


async def list_sent(
    session: AsyncSession,
    user_id: UUID,
    *,
    page: int,
    page_size: int,
) -> Page[SentShare]:
    share = tables.Share
    where = [share.user_id == user_id, share.revoked_at.is_(None)]
    total = await session.scalar(
        select(func.count()).select_from(share).where(*where),
    )
    rows = list(
        await session.scalars(
            select(share)
            .where(*where)
            .order_by(share.created_at.desc(), share.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size),
        ),
    )
    tracks = await get_tracks(session, [row.track_id for row in rows if row.track_id])
    playlists = await shared_playlists(session, rows)

    opened = tables.ShareOpen
    user = tables.User
    openers: dict[UUID, list[ShareOpener]] = {}
    if rows:
        for share_id, name, opens, last_opened_at in await session.execute(
            select(opened.share_id, user.name, opened.opens, opened.last_opened_at)
            .join(user, user.id == opened.user_id)
            .where(any_of(opened.share_id, [row.id for row in rows]))
            .order_by(opened.last_opened_at.desc(), opened.id.desc()),
        ):
            openers.setdefault(share_id, []).append(
                ShareOpener(
                    name=name or "",
                    opens=opens,
                    last_opened_at=last_opened_at,
                ),
            )

    return Page[SentShare](
        items=[
            SentShare(
                code=row.code,
                url=share_url(row.code),
                track=tracks.get(row.track_id) if row.track_id else None,
                playlist=playlists.get(row.id),
                created_at=row.created_at,
                anonymous_opens=row.anonymous_opens,
                opened_by=openers.get(row.id, []),
            )
            for row in rows
            if row.track_id in tracks or row.id in playlists
        ],
        page=page,
        page_size=page_size,
        total_count=total or 0,
        total_pages=math.ceil((total or 0) / page_size),
    )


async def list_received(
    session: AsyncSession,
    user_id: UUID,
    *,
    page: int,
    page_size: int,
) -> Page[ReceivedShare]:
    share = tables.Share
    opened = tables.ShareOpen
    user = tables.User
    where = [opened.user_id == user_id, share.revoked_at.is_(None)]
    total = await session.scalar(
        select(func.count())
        .select_from(opened)
        .join(share, share.id == opened.share_id)
        .where(*where),
    )
    rows = list(
        await session.execute(
            select(share, user.name, opened.last_opened_at)
            .select_from(opened)
            .join(share, share.id == opened.share_id)
            .join(user, user.id == share.user_id)
            .where(*where)
            .order_by(opened.last_opened_at.desc(), opened.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size),
        ),
    )
    shares = [row[0] for row in rows]
    tracks = await get_tracks(
        session,
        [item.track_id for item in shares if item.track_id],
    )
    playlists = await shared_playlists(session, shares)

    return Page[ReceivedShare](
        items=[
            ReceivedShare(
                code=item.code,
                track=tracks.get(item.track_id) if item.track_id else None,
                playlist=playlists.get(item.id),
                shared_by=Sharer(name=name or ""),
                opened_at=opened_at,
            )
            for item, name, opened_at in rows
            if item.track_id in tracks or item.id in playlists
        ],
        page=page,
        page_size=page_size,
        total_count=total or 0,
        total_pages=math.ceil((total or 0) / page_size),
    )
