from datetime import datetime
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.actions import shares as shares_actions
from src.repositories import shares as shares_repositories
from src.structs.models import Page
from src.structs.models.requests import ShareListRequest
from src.structs.models.requests import ShareRequest
from src.structs.models.responses import ReceivedShare
from src.structs.models.responses import SentShare
from src.structs.models.responses import SharedTrack
from src.structs.models.responses import ShareLink
from src.structs.models.responses import ShareOpened


async def share(
    session: AsyncSession,
    redis: Redis,
    request: ShareRequest,
    *,
    user_id: UUID,
) -> ShareLink:
    async with session.begin():
        return await shares_actions.share_track(
            session,
            redis,
            request.track_id,
            user_id=user_id,
        )


async def read_share(session: AsyncSession, code: str) -> SharedTrack:
    async with session.begin():
        return await shares_actions.read_share(session, code)


async def share_image(session: AsyncSession, redis: Redis, code: str) -> bytes:
    async with session.begin():
        shared = await shares_actions.read_share(session, code)

    return await shares_actions.share_image(redis, shared.track)


async def open_share(
    session: AsyncSession,
    code: str,
    *,
    user_id: UUID | None,
    now: datetime,
) -> ShareOpened | None:
    async with session.begin():
        return await shares_actions.open_share(
            session,
            code,
            user_id=user_id,
            now=now,
        )


async def list_sent(
    session: AsyncSession,
    request: ShareListRequest,
    *,
    user_id: UUID,
) -> Page[SentShare]:
    async with session.begin():
        return await shares_repositories.list_sent(
            session,
            user_id,
            page=request.page,
            page_size=request.page_size,
        )


async def list_received(
    session: AsyncSession,
    request: ShareListRequest,
    *,
    user_id: UUID,
) -> Page[ReceivedShare]:
    async with session.begin():
        return await shares_repositories.list_received(
            session,
            user_id,
            page=request.page,
            page_size=request.page_size,
        )


async def revoke_share(
    session: AsyncSession,
    code: str,
    *,
    user_id: UUID,
    now: datetime,
) -> None:
    async with session.begin():
        await shares_actions.revoke_share(session, code, user_id=user_id, now=now)
