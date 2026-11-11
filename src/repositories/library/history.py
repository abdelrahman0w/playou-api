import math
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy import exists
from sqlalchemy import func
from sqlalchemy import insert
from sqlalchemy import literal
from sqlalchemy import select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.catalog import get_tracks
from src.structs import tables
from src.structs.enums import Platforms
from src.structs.models import Page
from src.structs.models.responses import ListenedTrack


async def record_listen(
    session: AsyncSession,
    user_id: UUID,
    track_id: UUID,
    platform: Platforms,
    *,
    now: datetime,
) -> None:
    listen = tables.Listen
    user = tables.User
    await session.execute(
        insert(listen).from_select(
            ["user_id", "track_id", "platform", "played_at"],
            select(
                user.id,
                literal(track_id, listen.track_id.type),
                literal(platform, listen.platform.type),
                literal(now, listen.played_at.type),
            ).where(
                user.id == user_id,
                user.keep_history.is_(True),
                exists().where(tables.Track.id == track_id),
            ),
        ),
    )


async def list_history(
    session: AsyncSession,
    user_id: UUID,
    *,
    since: datetime,
    page: int,
    page_size: int,
) -> Page[ListenedTrack]:
    listen = tables.Listen
    shown = (listen.user_id == user_id, listen.played_at >= since)
    total = await session.scalar(
        select(func.count()).select_from(listen).where(*shown),
    )
    rows = list(
        await session.scalars(
            select(listen)
            .where(*shown)
            .order_by(listen.played_at.desc(), listen.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size),
        ),
    )
    tracks = await get_tracks(
        session,
        {row.track_id for row in rows},
        user_id=user_id,
    )

    return Page[ListenedTrack](
        items=[
            ListenedTrack(
                track=tracks[row.track_id],
                platform=row.platform,
                played_at=row.played_at,
            )
            for row in rows
            if row.track_id in tracks
        ],
        page=page,
        page_size=page_size,
        total_count=total or 0,
        total_pages=math.ceil((total or 0) / page_size),
    )


async def clear_history(session: AsyncSession, user_id: UUID) -> None:
    await session.execute(
        delete(tables.Listen).where(tables.Listen.user_id == user_id),
    )


async def last_listen(
    session: AsyncSession,
    user_id: UUID,
    platform: Platforms,
) -> datetime | None:
    listen = tables.Listen

    return await session.scalar(
        select(func.max(listen.played_at)).where(
            listen.user_id == user_id,
            listen.platform == platform,
        ),
    )


async def prune_listens(
    session: AsyncSession,
    *,
    before: datetime,
    limit: int,
) -> int:
    listen = tables.Listen
    oldest = select(listen.id).where(listen.played_at < before).limit(limit)
    result: CursorResult[Any] = await session.execute(  # type: ignore[assignment]
        delete(listen).where(listen.id.in_(oldest.scalar_subquery())),
    )

    return result.rowcount
