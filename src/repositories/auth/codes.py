from datetime import datetime
from typing import Any

from sqlalchemy import delete
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.structs import tables


async def replace_email_code(
    session: AsyncSession,
    email: str,
    *,
    code_hash: str,
    expires_at: datetime,
    now: datetime,
) -> None:
    code = tables.AuthEmailCode
    await session.execute(
        update(code)
        .where(code.email == email, code.consumed_at.is_(None))
        .values(consumed_at=now),
    )
    session.add(code(email=email, code_hash=code_hash, expires_at=expires_at))
    await session.flush()


async def get_live_code(
    session: AsyncSession,
    email: str,
    *,
    now: datetime,
) -> tables.AuthEmailCode | None:
    code = tables.AuthEmailCode

    return await session.scalar(
        select(code)
        .where(code.email == email, code.consumed_at.is_(None), code.expires_at > now)
        .order_by(code.created_at.desc())
        .limit(1)
        .with_for_update(),
    )


async def delete_spent_codes(session: AsyncSession, *, now: datetime) -> int:
    code = tables.AuthEmailCode
    result: CursorResult[Any] = await session.execute(  # type: ignore[assignment]
        delete(code).where(or_(code.expires_at <= now, code.consumed_at.is_not(None))),
    )

    return result.rowcount
