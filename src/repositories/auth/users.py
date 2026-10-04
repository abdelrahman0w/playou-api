from datetime import datetime
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.structs import tables
from src.structs.models.responses import AuthUser


def _to_user(row: tables.User) -> AuthUser:
    return AuthUser(
        id=row.id,
        email=row.email,
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
) -> tuple[AuthUser, bool]:
    user = tables.User
    statement = insert(user).values(
        email=email,
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


async def delete_user(session: AsyncSession, user_id: UUID) -> list[str]:
    hashes = list(
        await session.scalars(
            select(tables.AuthSession.token_hash).where(
                tables.AuthSession.user_id == user_id,
            ),
        ),
    )
    await session.execute(delete(tables.User).where(tables.User.id == user_id))

    return hashes


async def get_user_by_email(session: AsyncSession, email: str) -> UUID | None:
    return await session.scalar(
        select(tables.User.id).where(tables.User.email == email.strip().lower()),
    )
