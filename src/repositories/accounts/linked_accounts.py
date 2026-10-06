from collections.abc import Collection
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import case
from sqlalchemy import delete
from sqlalchemy import exists
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.structs import tables
from src.structs.enums import Platforms
from src.structs.enums import SyncStatuses
from src.structs.enums import SyncSubjects
from src.structs.models import AccountOwner
from src.structs.models import ExpiringAccount
from src.structs.models import StoredAccount


def _to_account(row: tables.LinkedAccount) -> StoredAccount:
    return StoredAccount(
        id=row.id,
        user_id=row.user_id,
        platform=row.platform,
        external_id=row.external_id,
        display_name=row.display_name,
        access_token=row.access_token,
        refresh_token=row.refresh_token,
        expires_at=row.expires_at,
        refresh_expires_at=row.refresh_expires_at,
        expiry_warned_at=row.expiry_warned_at,
        disconnect_warned_at=row.disconnect_warned_at,
        reconnect_required_at=row.reconnect_required_at,
        imported_at=row.imported_at,
        likes_read_at=row.likes_read_at,
        likes_total=row.likes_total,
        scopes=list(row.scopes),
        push_likes=row.push_likes,
        push_playlists=row.push_playlists,
        keep_in_sync=row.keep_in_sync,
        synced_at=row.synced_at,
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
    push_by_default: bool = True,
) -> StoredAccount:
    account = tables.LinkedAccount
    values = {
        "external_id": external_id,
        "display_name": display_name,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
        "refresh_expires_at": refresh_expires_at,
        "expiry_warned_at": None,
        "scopes": scopes,
        "reconnect_required_at": None,
        "disconnect_warned_at": None,
    }
    statement = insert(account).values(
        user_id=user_id,
        platform=platform,
        push_likes=push_by_default,
        push_playlists=push_by_default,
        **values,
    )
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
    now: datetime,
    before: datetime,
    limit: int,
) -> list[StoredAccount]:
    if not platforms:
        return []

    account = tables.LinkedAccount
    rows = await session.scalars(
        select(account)
        .where(
            account.platform.in_(platforms),
            account.reconnect_required_at.is_(None),
            account.refresh_token.is_not(None),
            account.refresh_expires_at > now,
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
    account = tables.LinkedAccount
    user = tables.User
    rows = await session.execute(
        select(account, user.email, user.locale)
        .join(user, user.id == account.user_id)
        .where(
            account.reconnect_required_at.is_(None),
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
    account_ids: list[UUID],
    *,
    now: datetime,
) -> None:
    await session.execute(
        update(tables.LinkedAccount)
        .where(tables.LinkedAccount.id.in_(account_ids))
        .values(expiry_warned_at=now),
    )


async def list_disconnected_to_warn(
    session: AsyncSession,
    *,
    limit: int,
) -> list[ExpiringAccount]:
    account = tables.LinkedAccount
    user = tables.User
    rows = await session.execute(
        select(account, user.email, user.locale)
        .join(user, user.id == account.user_id)
        .where(
            account.reconnect_required_at.is_not(None),
            account.disconnect_warned_at.is_(None),
        )
        .order_by(account.reconnect_required_at)
        .limit(limit),
    )

    return [
        ExpiringAccount(
            account=_to_account(row),
            owner=AccountOwner(email=email, locale=locale),
        )
        for row, email, locale in rows
    ]


async def list_disconnected_before(
    session: AsyncSession,
    *,
    before: datetime,
    limit: int,
) -> list[StoredAccount]:
    account = tables.LinkedAccount
    rows = await session.scalars(
        select(account)
        .where(account.reconnect_required_at <= before)
        .order_by(account.reconnect_required_at)
        .limit(limit),
    )

    return [_to_account(row) for row in rows]


async def mark_disconnect_warned(
    session: AsyncSession,
    account_ids: list[UUID],
    *,
    now: datetime,
) -> None:
    await session.execute(
        update(tables.LinkedAccount)
        .where(tables.LinkedAccount.id.in_(account_ids))
        .values(disconnect_warned_at=now),
    )


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
            reconnect_required_at=None,
            disconnect_warned_at=None,
            expiry_warned_at=case(
                (
                    account.refresh_expires_at.is_distinct_from(refresh_expires_at),
                    None,
                ),
                else_=account.expiry_warned_at,
            ),
        ),
    )


async def require_reconnect(
    session: AsyncSession,
    account_id: UUID,
    *,
    now: datetime,
) -> None:
    await session.execute(
        update(tables.LinkedAccount)
        .where(tables.LinkedAccount.id == account_id)
        .values(reconnect_required_at=now),
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


async def set_push_preferences(
    session: AsyncSession,
    user_id: UUID,
    platform: Platforms,
    *,
    push_likes: bool | None,
    push_playlists: bool | None,
    keep_in_sync: bool | None = None,
) -> StoredAccount | None:
    account = tables.LinkedAccount
    values = {
        key: value
        for key, value in (
            ("push_likes", push_likes),
            ("push_playlists", push_playlists),
            ("keep_in_sync", keep_in_sync),
        )
        if value is not None
    }
    if values:
        await session.execute(
            update(account)
            .where(account.user_id == user_id, account.platform == platform)
            .values(**values),
        )

    return await get_account(session, user_id, platform)


async def mark_imported(
    session: AsyncSession,
    account_id: UUID,
    *,
    now: datetime,
    likes_read: bool,
    likes_total: int | None,
) -> None:
    values: dict[str, datetime | int] = {"imported_at": now}
    if likes_read:
        values["likes_read_at"] = now
    if likes_total is not None:
        values["likes_total"] = likes_total

    await session.execute(
        update(tables.LinkedAccount)
        .where(tables.LinkedAccount.id == account_id)
        .values(**values),
    )


async def list_accounts_to_import(
    session: AsyncSession,
    *,
    platforms: Collection[Platforms],
    now: datetime,
    before: datetime,
    limit: int,
) -> list[StoredAccount]:
    if not platforms:
        return []

    account = tables.LinkedAccount
    operation = tables.SyncOperation
    imports = [
        operation.user_id == account.user_id,
        operation.platform == account.platform,
        operation.subject == SyncSubjects.IMPORT,
        operation.subject_id == account.id,
    ]
    rows = await session.scalars(
        select(account)
        .where(
            account.platform.in_(platforms),
            account.reconnect_required_at.is_(None),
            or_(account.refresh_expires_at.is_(None), account.refresh_expires_at > now),
            or_(account.imported_at.is_(None), account.imported_at < before),
            ~exists().where(*imports, operation.status == SyncStatuses.PENDING),
            ~exists().where(
                *imports,
                operation.status == SyncStatuses.FAILED,
                operation.finished_at >= before,
            ),
        )
        .order_by(account.imported_at.nulls_first())
        .limit(limit),
    )

    return [_to_account(row) for row in rows]


async def delete_accounts(session: AsyncSession, user_id: UUID) -> None:
    await session.execute(
        delete(tables.LinkedAccount).where(tables.LinkedAccount.user_id == user_id),
    )


async def mark_synced(session: AsyncSession, account_id: UUID, *, at: datetime) -> None:
    await session.execute(
        update(tables.LinkedAccount)
        .where(tables.LinkedAccount.id == account_id)
        .values(synced_at=at),
    )
