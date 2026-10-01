from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.structs import tables


async def create_session(
    session: AsyncSession,
    *,
    user_id: UUID,
    token_hash: str,
    expires_at: datetime,
    now: datetime,
    ip: str | None,
    user_agent: str | None,
) -> None:
    session.add(
        tables.AuthSession(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            last_seen_at=now,
            ip=ip,
            user_agent=user_agent,
        ),
    )
    await session.flush()


async def get_live_session(
    session: AsyncSession,
    token_hash: str,
    *,
    now: datetime,
) -> tables.AuthSession | None:
    return await session.scalar(
        select(tables.AuthSession).where(
            tables.AuthSession.token_hash == token_hash,
            tables.AuthSession.expires_at > now,
        ),
    )


async def extend_session(
    session: AsyncSession,
    session_id: int,
    *,
    expires_at: datetime,
    now: datetime,
) -> None:
    await session.execute(
        update(tables.AuthSession)
        .where(tables.AuthSession.id == session_id)
        .values(expires_at=expires_at, last_seen_at=now),
    )


async def delete_session(
    session: AsyncSession,
    token_hash: str,
) -> None:
    await session.execute(
        delete(tables.AuthSession).where(tables.AuthSession.token_hash == token_hash),
    )


async def delete_expired_sessions(
    session: AsyncSession,
    *,
    now: datetime,
) -> int:
    result: CursorResult[Any] = await session.execute(  # type: ignore[assignment]
        delete(tables.AuthSession).where(tables.AuthSession.expires_at <= now),
    )

    return result.rowcount
