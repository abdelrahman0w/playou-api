from collections.abc import Collection
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.structs import tables
from src.structs.enums import Platforms
from src.structs.enums import SyncOutcomes
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
    subjects: Collection[SyncSubjects],
    user_id: UUID | None = None,
) -> SyncTask | None:
    operation = tables.SyncOperation
    statement = select(operation).where(
        operation.status == SyncStatuses.PENDING,
        operation.next_attempt_at <= now,
        operation.subject.in_(subjects),
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


async def claim_alike(
    session: AsyncSession,
    task: SyncTask,
    *,
    now: datetime,
    limit: int,
) -> list[SyncTask]:
    operation = tables.SyncOperation
    rows = await session.scalars(
        select(operation)
        .where(
            operation.status == SyncStatuses.PENDING,
            operation.next_attempt_at <= now,
            operation.user_id == task.user_id,
            operation.platform == task.platform,
            operation.subject == task.subject,
            operation.id != task.id,
        )
        .order_by(operation.id)
        .limit(limit)
        .with_for_update(skip_locked=True),
    )

    return [
        SyncTask(
            id=row.id,
            user_id=row.user_id,
            platform=row.platform,
            subject=row.subject,
            subject_id=row.subject_id,
            attempts=row.attempts,
        )
        for row in rows
    ]


async def finish(
    session: AsyncSession,
    operation_id: int,
    outcome: SyncOutcomes,
    *,
    now: datetime,
    error: str | None = None,
) -> None:
    await session.execute(
        update(tables.SyncOperation)
        .where(tables.SyncOperation.id == operation_id)
        .values(outcome=outcome, finished_at=now, last_error=error),
    )


async def save_progress(
    session: AsyncSession,
    operation_id: int,
    progress: dict[str, Any],
) -> None:
    await session.execute(
        update(tables.SyncOperation)
        .where(tables.SyncOperation.id == operation_id)
        .values(progress=progress),
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


async def enqueue_import(
    session: AsyncSession,
    *,
    user_id: UUID,
    platform: Platforms,
    account_id: UUID,
    now: datetime,
) -> None:
    await session.execute(
        insert(tables.SyncOperation)
        .values(
            user_id=user_id,
            platform=platform,
            subject=SyncSubjects.IMPORT,
            subject_id=account_id,
            attempts=0,
            next_attempt_at=now,
        )
        .on_conflict_do_nothing(
            index_elements=["user_id", "platform", "subject", "subject_id"],
            index_where=text("status = 'PENDING'"),
        ),
    )


async def lease_imports(
    session: AsyncSession,
    *,
    now: datetime,
    until: datetime,
    limit: int,
    user_id: UUID | None = None,
) -> list[SyncTask]:
    operation = tables.SyncOperation
    rows = list(
        await session.scalars(
            select(operation)
            .where(
                operation.status == SyncStatuses.PENDING,
                operation.next_attempt_at <= now,
                operation.subject == SyncSubjects.IMPORT,
                *([operation.user_id == user_id] if user_id is not None else []),
            )
            .order_by(operation.next_attempt_at, operation.id)
            .limit(limit)
            .with_for_update(skip_locked=True),
        ),
    )
    if rows:
        await session.execute(
            update(operation)
            .where(operation.id.in_([row.id for row in rows]))
            .values(next_attempt_at=until),
        )

    return [
        SyncTask(
            id=row.id,
            user_id=row.user_id,
            platform=row.platform,
            subject=row.subject,
            subject_id=row.subject_id,
            attempts=row.attempts,
        )
        for row in rows
    ]


async def pending_subject_ids(
    session: AsyncSession,
    *,
    user_id: UUID,
    platform: Platforms,
    subject: SyncSubjects,
) -> set[UUID]:
    operation = tables.SyncOperation

    return set(
        await session.scalars(
            select(operation.subject_id).where(
                operation.user_id == user_id,
                operation.platform == platform,
                operation.subject == subject,
                operation.status == SyncStatuses.PENDING,
            ),
        ),
    )


async def latest_imports(
    session: AsyncSession,
    user_id: UUID,
) -> dict[UUID, tuple[SyncStatuses, str | None, dict[str, Any] | None]]:
    operation = tables.SyncOperation
    rows = await session.execute(
        select(
            operation.subject_id,
            operation.status,
            operation.last_error,
            operation.progress,
        )
        .where(
            operation.user_id == user_id,
            operation.subject == SyncSubjects.IMPORT,
        )
        .ext(distinct_on(operation.subject_id))
        .order_by(operation.subject_id.desc(), operation.id.desc()),
    )

    return {
        account_id: (status, error, progress)
        for account_id, status, error, progress in rows
    }
