from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.structs import tables
from src.structs.models.responses import AuthUser


def _to_user(row: tables.User) -> AuthUser:
    return AuthUser(
        id=row.id,
        email=row.email,
        name=row.name,
        locale=row.locale,
        created_at=row.created_at,
        last_sign_in_at=row.last_sign_in_at,
    )


async def sign_in_user(
    session: AsyncSession,
    email: str,
    *,
    locale: str,
    now: datetime,
    name: str | None = None,
) -> tuple[AuthUser, bool]:
    user = tables.User
    statement = insert(user).values(
        email=email,
        name=name,
        locale=locale,
        email_verified_at=now,
        last_sign_in_at=now,
    )
    row = (
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["email"],
                set_={"last_sign_in_at": now, "updated_at": func.now()},
            ).returning(user),
        )
    ).scalar_one()

    return _to_user(row), row.created_at == row.updated_at


async def get_user(session: AsyncSession, user_id: UUID) -> AuthUser | None:
    row = await session.get(tables.User, user_id)

    return _to_user(row) if row is not None else None


async def session_hashes(
    session: AsyncSession,
    user_id: UUID,
) -> list[str]:
    return list(
        await session.scalars(
            select(tables.AuthSession.token_hash).where(
                tables.AuthSession.user_id == user_id,
            ),
        ),
    )


async def user_has_name(
    session: AsyncSession,
    user_id: UUID,
) -> bool:
    name = await session.scalar(
        select(tables.User.name).where(tables.User.id == user_id),
    )

    return name is not None


async def delete_user(session: AsyncSession, user_id: UUID) -> list[str]:
    hashes = await session_hashes(session, user_id)
    await session.execute(delete(tables.User).where(tables.User.id == user_id))

    return hashes


async def get_user_by_email(session: AsyncSession, email: str) -> UUID | None:
    return await session.scalar(
        select(tables.User.id).where(tables.User.email == email.strip().lower()),
    )


async def lock_user(session: AsyncSession, user_id: UUID) -> AuthUser | None:
    row = await session.scalar(
        select(tables.User)
        .where(tables.User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True),
    )

    return _to_user(row) if row is not None else None


async def set_name(session: AsyncSession, user_id: UUID, name: str) -> AuthUser:
    row = (
        await session.execute(
            update(tables.User)
            .where(tables.User.id == user_id)
            .values(name=name)
            .returning(tables.User),
        )
    ).scalar_one()

    return _to_user(row)


async def name_changes_since(
    session: AsyncSession,
    user_id: UUID,
    *,
    since: datetime,
) -> list[datetime]:
    change = tables.NameChange

    return list(
        await session.scalars(
            select(change.changed_at)
            .where(change.user_id == user_id, change.changed_at > since)
            .order_by(change.changed_at),
        ),
    )


async def record_name_change(
    session: AsyncSession,
    user_id: UUID,
    *,
    now: datetime,
) -> None:
    session.add(tables.NameChange(user_id=user_id, changed_at=now))
    await session.flush()


async def delete_name_changes(session: AsyncSession, *, before: datetime) -> int:
    change = tables.NameChange
    result: CursorResult[Any] = await session.execute(  # type: ignore[assignment]
        delete(change).where(change.changed_at <= before),
    )

    return result.rowcount
