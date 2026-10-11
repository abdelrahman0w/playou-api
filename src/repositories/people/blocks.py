from uuid import UUID

from sqlalchemy import delete
from sqlalchemy import exists
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.structs import tables


async def block_user(session: AsyncSession, blocker_id: UUID, blocked_id: UUID) -> None:
    await session.execute(
        insert(tables.UserBlock)
        .values(blocker_id=blocker_id, blocked_id=blocked_id)
        .on_conflict_do_nothing(index_elements=["blocker_id", "blocked_id"]),
    )
    follow = tables.Follow
    await session.execute(
        delete(follow).where(
            or_(
                (follow.follower_id == blocker_id) & (follow.followee_id == blocked_id),
                (follow.follower_id == blocked_id) & (follow.followee_id == blocker_id),
            ),
        ),
    )


async def unblock_user(
    session: AsyncSession, blocker_id: UUID, blocked_id: UUID
) -> None:
    block = tables.UserBlock
    await session.execute(
        delete(block).where(
            block.blocker_id == blocker_id, block.blocked_id == blocked_id
        ),
    )


async def blocked_between(session: AsyncSession, first: UUID, second: UUID) -> bool:
    block = tables.UserBlock

    return bool(
        await session.scalar(
            select(
                exists().where(
                    or_(
                        (block.blocker_id == first) & (block.blocked_id == second),
                        (block.blocker_id == second) & (block.blocked_id == first),
                    ),
                ),
            ),
        ),
    )


async def has_blocked(
    session: AsyncSession, blocker_id: UUID, blocked_id: UUID
) -> bool:
    block = tables.UserBlock

    return bool(
        await session.scalar(
            select(
                exists().where(
                    block.blocker_id == blocker_id,
                    block.blocked_id == blocked_id,
                ),
            ),
        ),
    )
