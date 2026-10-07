import math
from datetime import datetime
from itertools import batched
from uuid import UUID

from sqlalchemy import case
from sqlalchemy import exists
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from src.repositories.catalog import get_tracks
from src.structs import tables
from src.structs.enums import LikeSorts
from src.structs.enums import Platforms
from src.structs.enums import RemovedBy
from src.structs.models import LikeSyncState
from src.structs.models import Page
from src.structs.models.responses import CatalogTrack
from src.structs.models.responses import LikedTrack
from src.utils.search import matching
from src.utils.sql import ROWS_PER_INSERT
from src.utils.sql import any_of


def _to_liked(
    row: tables.Like,
    tracks: dict[UUID, CatalogTrack],
) -> LikedTrack:
    return LikedTrack(
        track=tracks[row.track_id],
        liked_at=row.liked_at,
        removed_at=row.removed_at,
        removed_by=row.removed_by,
    )


async def set_like(
    session: AsyncSession,
    user_id: UUID,
    track_id: UUID,
    *,
    now: datetime,
) -> None:
    like = tables.Like
    await session.execute(
        insert(like)
        .values(user_id=user_id, track_id=track_id, liked_at=now)
        .on_conflict_do_update(
            index_elements=["user_id", "track_id"],
            set_={
                "liked_at": now,
                "removed_at": None,
                "removed_by": None,
                "updated_at": func.now(),
            },
        ),
    )


async def remove_like(
    session: AsyncSession,
    user_id: UUID,
    track_id: UUID,
    *,
    now: datetime,
    removed_by: RemovedBy,
) -> bool:
    like = tables.Like
    removed = await session.scalar(
        update(like)
        .where(
            like.user_id == user_id,
            like.track_id == track_id,
            like.removed_at.is_(None),
        )
        .values(removed_at=now, removed_by=removed_by)
        .returning(like.id),
    )

    return removed is not None


async def get_like(
    session: AsyncSession,
    user_id: UUID,
    track_id: UUID,
) -> LikedTrack | None:
    like = tables.Like
    row = await session.scalar(
        select(like).where(like.user_id == user_id, like.track_id == track_id),
    )
    if row is None:
        return None

    return _to_liked(
        row,
        await get_tracks(session, [row.track_id]),
    )


async def liked_track_ids(
    session: AsyncSession,
    user_id: UUID,
) -> list[UUID]:
    like = tables.Like

    return list(
        await session.scalars(
            select(like.track_id).where(
                like.user_id == user_id,
                like.removed_at.is_(None),
            ),
        ),
    )


async def list_likes(
    session: AsyncSession,
    user_id: UUID,
    *,
    page: int,
    page_size: int,
    include_removed: bool,
    platform: Platforms | None = None,
    query: str | None = None,
    sort: LikeSorts = LikeSorts.RECENT,
) -> Page[LikedTrack]:
    like = tables.Like
    track = tables.Track
    where = [like.user_id == user_id]
    if not include_removed:
        where.append(like.removed_at.is_(None))
    if platform is not None:
        source = tables.TrackSource
        where.append(
            exists().where(
                source.track_id == like.track_id,
                source.platform == platform,
            ),
        )
    if query:
        searched = func.track_search_text(track.title, track.artists, track.album)
        where.append(
            exists().where(track.id == like.track_id, *matching(searched, query)),
        )

    total = await session.scalar(
        select(func.count()).select_from(like).where(*where),
    )
    sorted_by = aliased(tables.Track)
    order = {
        LikeSorts.RECENT: (like.liked_at.desc(), like.id.desc()),
        LikeSorts.OLDEST: (like.liked_at, like.id),
        LikeSorts.TITLE: (sorted_by.sort_title, like.id),
        LikeSorts.ARTIST: (sorted_by.sort_artist, sorted_by.sort_title, like.id),
    }[sort]
    rows = list(
        await session.scalars(
            select(like)
            .join(sorted_by, sorted_by.id == like.track_id)
            .where(*where)
            .order_by(*order)
            .offset((page - 1) * page_size)
            .limit(page_size),
        ),
    )
    tracks = await get_tracks(session, [row.track_id for row in rows])

    return Page[LikedTrack](
        items=[_to_liked(row, tracks) for row in rows],
        page=page,
        page_size=page_size,
        total_count=total or 0,
        total_pages=math.ceil((total or 0) / page_size),
    )


async def like_sync_states(
    session: AsyncSession,
    user_id: UUID,
    track_ids: list[UUID],
    platform: Platforms,
) -> dict[UUID, LikeSyncState]:
    like = tables.Like
    source = tables.TrackSource
    rows = await session.execute(
        select(like.track_id, like.removed_at, source.platform_id)
        .select_from(like)
        .outerjoin(
            source,
            (source.track_id == like.track_id) & (source.platform == platform),
        )
        .where(like.user_id == user_id, any_of(like.track_id, track_ids)),
    )

    return {
        track_id: LikeSyncState(liked=removed_at is None, platform_id=platform_id)
        for track_id, removed_at, platform_id in rows
    }


async def liked_platform_ids(
    session: AsyncSession,
    user_id: UUID,
    platform: Platforms,
) -> dict[str, UUID]:
    like = tables.Like
    source = tables.TrackSource
    rows = await session.execute(
        select(source.platform_id, like.track_id)
        .select_from(like)
        .join(
            source,
            (source.track_id == like.track_id) & (source.platform == platform),
        )
        .where(like.user_id == user_id, like.removed_at.is_(None)),
    )

    return {platform_id: track_id for platform_id, track_id in rows}


async def import_likes(
    session: AsyncSession,
    user_id: UUID,
    likes: list[tuple[UUID, datetime]],
    *,
    platform: Platforms,
) -> None:
    if not likes:
        return

    like = tables.Like
    for chunk in batched(dict(likes).items(), ROWS_PER_INSERT, strict=False):
        statement = insert(like).values(
            [
                {
                    "user_id": user_id,
                    "track_id": track_id,
                    "liked_at": liked_at,
                    "imported_from": platform,
                }
                for track_id, liked_at in chunk
            ],
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["user_id", "track_id"],
                set_={
                    "liked_at": case(
                        (
                            like.removed_at.is_(None),
                            func.greatest(like.liked_at, statement.excluded.liked_at),
                        ),
                        else_=statement.excluded.liked_at,
                    ),
                    "removed_at": None,
                    "removed_by": None,
                    "updated_at": func.now(),
                },
                where=or_(
                    like.removed_at.is_not(None),
                    like.liked_at < statement.excluded.liked_at,
                ),
            ),
        )


async def remove_likes(
    session: AsyncSession,
    user_id: UUID,
    track_ids: list[UUID],
    *,
    now: datetime,
    removed_by: RemovedBy,
) -> None:
    if not track_ids:
        return

    like = tables.Like
    await session.execute(
        update(like)
        .where(
            like.user_id == user_id,
            any_of(like.track_id, track_ids),
            like.removed_at.is_(None),
        )
        .values(removed_at=now, removed_by=removed_by),
    )
