from collections.abc import Collection
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import case
from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.structs import tables
from src.structs.enums import AccountStatuses
from src.structs.enums import Platforms
from src.structs.models import AccountOwner
from src.structs.models import ExpiringAccount
from src.structs.models import StoredAccount


def _to_account(row: tables.LinkedAccount) -> StoredAccount:
    return StoredAccount(
        id=row.id,
        user_id=row.user_id,
        platform=row.platform,
        status=row.status,
        external_id=row.external_id,
        display_name=row.display_name,
        access_token=row.access_token,
        refresh_token=row.refresh_token,
        expires_at=row.expires_at,
        refresh_expires_at=row.refresh_expires_at,
        expiry_warned_at=row.expiry_warned_at,
        scopes=list(row.scopes),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def upsert_account(
    session: AsyncSession,
    *,
    user_id: UUID,
    platform: Platforms,
    external_id: str,
    display_name: str | None,
    access_token: str,
    refresh_token: str | None,
    expires_at: datetime | None,
    refresh_expires_at: datetime | None,
    scopes: list[str],
) -> StoredAccount:
    account = tables.LinkedAccount
    values = {
        "external_id": external_id,
        "display_name": display_name,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
        "refresh_expires_at": refresh_expires_at,
        # linking again is a new expiry, so a new warning
        "expiry_warned_at": None,
        "scopes": scopes,
        "status": AccountStatuses.ACTIVE,
    }
    statement = insert(account).values(user_id=user_id, platform=platform, **values)
    row = (
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["user_id", "platform"],
                set_=values | {"updated_at": func.now()},
            ).returning(account),
        )
    ).scalar_one()

    return _to_account(row)


async def get_account(
    session: AsyncSession,
    user_id: UUID,
    platform: Platforms,
) -> StoredAccount | None:
    account = tables.LinkedAccount
    row = await session.scalar(
        select(account).where(account.user_id == user_id, account.platform == platform),
    )

    return _to_account(row) if row is not None else None


async def get_account_by_id(
    session: AsyncSession,
    account_id: UUID,
    *,
    for_update: bool = False,
) -> StoredAccount | None:
    statement = select(tables.LinkedAccount).where(
        tables.LinkedAccount.id == account_id
    )
    row = await session.scalar(
        statement.with_for_update() if for_update else statement,
    )

    return _to_account(row) if row is not None else None


async def list_accounts(
    session: AsyncSession,
    user_id: UUID,
) -> list[StoredAccount]:
    account = tables.LinkedAccount
    rows = await session.scalars(
        select(account).where(account.user_id == user_id).order_by(account.created_at),
    )

    return [_to_account(row) for row in rows]


async def list_expiring_accounts(
    session: AsyncSession,
    *,
    platforms: Collection[Platforms],
    before: datetime,
    limit: int,
) -> list[StoredAccount]:
    """The active accounts whose refresh token expires before then, the soonest first"""
    if not platforms:
        return []

    account = tables.LinkedAccount
    rows = await session.scalars(
        select(account)
        .where(
            account.platform.in_(platforms),
            account.status == AccountStatuses.ACTIVE,
            account.refresh_token.is_not(None),
            account.refresh_expires_at <= before,
        )
        .order_by(account.refresh_expires_at)
        .limit(limit),
    )

    return [_to_account(row) for row in rows]


async def list_accounts_to_warn(
    session: AsyncSession,
    *,
    now: datetime,
    before: datetime,
    limit: int,
) -> list[ExpiringAccount]:
    """The active accounts expiring before then, not yet warned, the soonest first"""
    account = tables.LinkedAccount
    user = tables.User
    rows = await session.execute(
        select(account, user.email, user.locale)
        .join(user, user.id == account.user_id)
        .where(
            account.status == AccountStatuses.ACTIVE,
            account.refresh_expires_at > now,
            account.refresh_expires_at <= before,
            account.expiry_warned_at.is_(None),
        )
        .order_by(account.refresh_expires_at)
        .limit(limit),
    )

    return [
        ExpiringAccount(
            account=_to_account(row),
            owner=AccountOwner(email=email, locale=locale),
        )
        for row, email, locale in rows
    ]


async def mark_warned(
    session: AsyncSession,
    account_id: UUID,
    *,
    now: datetime,
) -> None:
    await session.execute(
        update(tables.LinkedAccount)
        .where(tables.LinkedAccount.id == account_id)
        .values(expiry_warned_at=now),
    )


async def mark_expired_accounts(
    session: AsyncSession,
    *,
    now: datetime,
) -> int:
    """Marks the active accounts whose refresh token expired, to be linked again"""
    account = tables.LinkedAccount
    result: CursorResult[Any] = await session.execute(  # type: ignore[assignment]
        update(account)
        .where(
            account.status == AccountStatuses.ACTIVE,
            account.refresh_expires_at <= now,
        )
        .values(status=AccountStatuses.NEEDS_RECONNECT),
    )

    return result.rowcount


async def update_tokens(
    session: AsyncSession,
    account_id: UUID,
    *,
    access_token: str,
    refresh_token: str | None,
    expires_at: datetime | None,
    refresh_expires_at: datetime | None,
) -> None:
    account = tables.LinkedAccount
    await session.execute(
        update(account)
        .where(account.id == account_id)
        .values(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            refresh_expires_at=refresh_expires_at,
            # an expiry that moved on is a new one, so a new warning
            expiry_warned_at=case(
                (
                    account.refresh_expires_at.is_distinct_from(refresh_expires_at),
                    None,
                ),
                else_=account.expiry_warned_at,
            ),
            status=AccountStatuses.ACTIVE,
        ),
    )


async def set_status(
    session: AsyncSession,
    account_id: UUID,
    status: AccountStatuses,
) -> None:
    await session.execute(
        update(tables.LinkedAccount)
        .where(tables.LinkedAccount.id == account_id)
        .values(status=status),
    )


async def delete_account(
    session: AsyncSession,
    user_id: UUID,
    platform: Platforms,
) -> bool:
    account = tables.LinkedAccount
    result: CursorResult[Any] = await session.execute(  # type: ignore[assignment]
        delete(account).where(account.user_id == user_id, account.platform == platform),
    )

    return bool(result.rowcount)
