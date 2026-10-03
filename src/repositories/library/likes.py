import math
from datetime import datetime
from uuid import UUID

from sqlalchemy import case
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.catalog import get_tracks
from src.structs import tables
from src.structs.enums import Platforms
from src.structs.enums import RemovedBy
from src.structs.models import LikeSyncState
from src.structs.models import Page
from src.structs.models.responses import CatalogTrack
from src.structs.models.responses import LikedTrack


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
                "liked_at": case(
                    (like.removed_at.is_(None), like.liked_at),
                    else_=now,
                ),
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


async def list_likes(
    session: AsyncSession,
    user_id: UUID,
    *,
    page: int,
    page_size: int,
    include_removed: bool,
) -> Page[LikedTrack]:
    like = tables.Like
    where = [like.user_id == user_id]
    if not include_removed:
        where.append(like.removed_at.is_(None))

    total = await session.scalar(
        select(func.count()).select_from(like).where(*where),
    )
    rows = list(
        await session.scalars(
            select(like)
            .where(*where)
            .order_by(like.liked_at.desc(), like.id.desc())
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


async def like_sync_state(
    session: AsyncSession,
    user_id: UUID,
    track_id: UUID,
    platform: Platforms,
) -> LikeSyncState | None:
    like = tables.Like
    source = tables.TrackSource
    row = (
        await session.execute(
            select(like.removed_at, source.platform_id)
            .select_from(like)
            .outerjoin(
                source,
                (source.track_id == like.track_id) & (source.platform == platform),
            )
            .where(like.user_id == user_id, like.track_id == track_id),
        )
    ).first()
    if row is None:
        return None

    removed_at, platform_id = row

    return LikeSyncState(
        liked=removed_at is None,
        platform_id=platform_id,
    )
