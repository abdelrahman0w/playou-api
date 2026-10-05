from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.structs import tables
from src.structs.models import StoredPlaybackSession
from src.structs.models.requests import SavePlaybackSessionRequest
from src.structs.models.responses import PlaybackSessionSaved


def _stored(row: tables.PlaybackSession) -> StoredPlaybackSession:
    return StoredPlaybackSession(
        user_id=row.user_id,
        device_id=row.device_id,
        device_name=row.device_name,
        platform=row.platform,
        source=row.source,
        track_ids=list(row.track_ids),
        cursor=row.cursor,
        current_track_id=row.current_track_id,
        up_next=list(row.up_next),
        playing=row.playing,
        position_ms=row.position_ms,
        position_at=row.position_at,
        version=row.version,
    )


async def get_session(
    session: AsyncSession,
    user_id: UUID,
) -> StoredPlaybackSession | None:
    row = await session.get(tables.PlaybackSession, user_id, populate_existing=True)

    return _stored(row) if row else None


async def save_session(
    session: AsyncSession,
    user_id: UUID,
    request: SavePlaybackSessionRequest,
    *,
    now: datetime,
) -> PlaybackSessionSaved | None:
    table = tables.PlaybackSession
    values = request.model_dump(exclude={"version"}) | {"position_at": now}

    if request.version == 0:
        statement: Any = (
            insert(table)
            .values(user_id=user_id, version=1, updated_at=now, **values)
            .on_conflict_do_nothing(index_elements=[table.user_id])
            .returning(table.version, table.position_at)
        )
    else:
        statement = (
            update(table)
            .where(table.user_id == user_id, table.version == request.version)
            .values(version=table.version + 1, updated_at=now, **values)
            .returning(table.version, table.position_at)
        )

    row = (await session.execute(statement)).one_or_none()

    return (
        PlaybackSessionSaved(version=row.version, position_at=row.position_at)
        if row
        else None
    )


async def claim_session(
    session: AsyncSession,
    user_id: UUID,
    *,
    device_id: str,
    device_name: str,
    position_ms: int,
    now: datetime,
) -> StoredPlaybackSession | None:
    table = tables.PlaybackSession
    row = (
        await session.execute(
            update(table)
            .where(table.user_id == user_id)
            .values(
                device_id=device_id,
                device_name=device_name,
                playing=False,
                position_ms=position_ms,
                position_at=now,
                version=table.version + 1,
                updated_at=now,
            )
            .returning(table),
        )
    ).scalar_one_or_none()

    return _stored(row) if row else None


async def delete_session(session: AsyncSession, user_id: UUID) -> None:
    await session.execute(
        delete(tables.PlaybackSession).where(tables.PlaybackSession.user_id == user_id),
    )


async def delete_stale_sessions(session: AsyncSession, *, before: datetime) -> int:
    table = tables.PlaybackSession
    result: CursorResult[Any] = await session.execute(  # type: ignore[assignment]
        delete(table).where(table.updated_at < before),
    )

    return result.rowcount
