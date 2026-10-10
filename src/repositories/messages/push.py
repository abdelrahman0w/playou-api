from collections.abc import Collection
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.structs import tables
from src.utils.sql import any_of


async def save_subscription(
    session: AsyncSession,
    user_id: UUID,
    *,
    endpoint: str,
    p256dh: str,
    auth: str,
) -> None:
    subscription = tables.PushSubscription
    values = {"user_id": user_id, "p256dh": p256dh, "auth": auth}
    await session.execute(
        insert(subscription)
        .values(endpoint=endpoint, **values)
        .on_conflict_do_update(
            index_elements=["endpoint"],
            set_={**values, "updated_at": func.now()},
        ),
    )


async def delete_subscription(
    session: AsyncSession, user_id: UUID, endpoint: str
) -> None:
    subscription = tables.PushSubscription
    await session.execute(
        delete(subscription).where(
            subscription.user_id == user_id,
            subscription.endpoint == endpoint,
        ),
    )


async def subscriptions_of(
    session: AsyncSession,
    user_ids: Collection[UUID],
) -> list[tuple[tables.PushSubscription, str]]:
    if not user_ids:
        return []

    subscription = tables.PushSubscription
    user = tables.User
    rows = await session.execute(
        select(subscription, user.locale)
        .join(user, user.id == subscription.user_id)
        .where(any_of(subscription.user_id, user_ids)),
    )

    return [(row[0], row[1]) for row in rows]


async def forget_endpoints(session: AsyncSession, endpoints: Collection[str]) -> None:
    if not endpoints:
        return

    subscription = tables.PushSubscription
    await session.execute(
        delete(subscription).where(any_of(subscription.endpoint, endpoints)),
    )


async def user_name(session: AsyncSession, user_id: UUID) -> str | None:
    return await session.scalar(
        select(tables.User.name).where(tables.User.id == user_id)
    )
