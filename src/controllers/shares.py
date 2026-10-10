from datetime import datetime
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.actions import shares as shares_actions
from src.exceptions import NotFoundError
from src.repositories import shares as shares_repositories
from src.structs.models import Page
from src.structs.models.requests import ShareListRequest
from src.structs.models.requests import ShareRequest
from src.structs.models.responses import CatalogTrack
from src.structs.models.responses import ReceivedShare
from src.structs.models.responses import SentShare
from src.structs.models.responses import Shared
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
        return await shares_actions.share(
            session,
            redis,
            track_id=request.track_id,
            playlist_id=request.playlist_id,
            user_id=user_id,
        )


async def read_share(session: AsyncSession, code: str) -> Shared:
    async with session.begin():
        return await shares_actions.read_share(session, code)


async def share_items(
    session: AsyncSession,
    code: str,
    request: ShareListRequest,
) -> Page[CatalogTrack]:
    async with session.begin():
        return await shares_actions.share_items(session, code, page=request.page)


async def share_image(session: AsyncSession, redis: Redis, code: str) -> bytes:
    async with session.begin():
        shared = await shares_actions.read_share(session, code)

    if shared.playlist is not None:
        return await shares_actions.share_image(
            redis,
            title=shared.playlist.name,
            subtitle=f"♫ {shared.playlist.item_count}",
            cover_url=shared.playlist.cover_url,
        )

    track = shared.track
    if track is None:
        raise NotFoundError("This link is no longer available")

    return await shares_actions.share_image(
        redis,
        title=track.title,
        subtitle=", ".join(track.artists),
        cover_url=track.artwork_url or track.thumbnail_url,
    )


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
