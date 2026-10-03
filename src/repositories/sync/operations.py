from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.structs import tables
from src.structs.enums import Platforms
from src.structs.enums import SyncStatuses
from src.structs.enums import SyncSubjects
from src.structs.models import SyncTask


async def enqueue(
    session: AsyncSession,
    *,
    user_id: UUID,
    platform: Platforms,
    subject: SyncSubjects,
    subject_id: UUID,
    now: datetime,
) -> None:
    operation = tables.SyncOperation
    await session.execute(
        insert(operation)
        .values(
            user_id=user_id,
            platform=platform,
            subject=subject,
            subject_id=subject_id,
            status=SyncStatuses.PENDING,
            attempts=0,
            next_attempt_at=now,
        )
        .on_conflict_do_update(
            index_elements=["user_id", "platform", "subject", "subject_id"],
            index_where=text("status = 'PENDING'"),
            set_={"next_attempt_at": now, "updated_at": func.now()},
        ),
    )


async def claim_next(
    session: AsyncSession,
    *,
    now: datetime,
    user_id: UUID | None = None,
) -> SyncTask | None:
    """The oldest due operation, locked until the transaction ends, skipping taken"""
    operation = tables.SyncOperation
    statement = select(operation).where(
        operation.status == SyncStatuses.PENDING,
        operation.next_attempt_at <= now,
    )
    if user_id is not None:
        statement = statement.where(operation.user_id == user_id)

    row = await session.scalar(
        statement.order_by(operation.id).limit(1).with_for_update(skip_locked=True),
    )
    if row is None:
        return None

    return SyncTask(
        id=row.id,
        user_id=row.user_id,
        platform=row.platform,
        subject=row.subject,
        subject_id=row.subject_id,
        attempts=row.attempts,
    )


async def finish(
    session: AsyncSession,
    operation_id: int,
    status: SyncStatuses,
    *,
    now: datetime,
    error: str | None = None,
) -> None:
    await session.execute(
        update(tables.SyncOperation)
        .where(tables.SyncOperation.id == operation_id)
        .values(status=status, finished_at=now, last_error=error),
    )


async def retry_later(
    session: AsyncSession,
    operation_id: int,
    *,
    at: datetime,
    error: str,
    count_attempt: bool,
) -> None:
    operation = tables.SyncOperation
    await session.execute(
        update(operation)
        .where(operation.id == operation_id)
        .values(
            next_attempt_at=at,
            last_error=error,
            attempts=operation.attempts + 1 if count_attempt else operation.attempts,
        ),
    )


async def prune_finished(
    session: AsyncSession,
    *,
    before: datetime,
) -> int:
    operation = tables.SyncOperation
    result: CursorResult[Any] = await session.execute(  # type: ignore[assignment]
        delete(operation).where(
            operation.status != SyncStatuses.PENDING,
            operation.finished_at < before,
        ),
    )

    return result.rowcount
