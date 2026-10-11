from datetime import datetime
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.actions import people as people_actions
from src.structs.enums import FollowStates
from src.structs.models import Page
from src.structs.models.requests import PeoplePageRequest
from src.structs.models.responses import Person
from src.structs.models.responses import Profile
from src.structs.models.responses import ProfilePlaylistSongs
from src.structs.models.responses import UsernameCheck


async def search(
    session: AsyncSession,
    redis: Redis,
    query: str,
    *,
    viewer_id: UUID,
) -> list[Person]:
    async with session.begin():
        return await people_actions.search(session, redis, query, viewer_id=viewer_id)


async def check_username(
    session: AsyncSession,
    redis: Redis,
    username: str,
    *,
    viewer_id: UUID | None,
    ip: str | None,
) -> UsernameCheck:
    async with session.begin():
        return await people_actions.check_username(
            session,
            redis,
            username,
            viewer_id=viewer_id,
            ip=ip,
        )


async def profile(session: AsyncSession, username: str, *, viewer_id: UUID) -> Profile:
    async with session.begin():
        return await people_actions.profile(session, username, viewer_id=viewer_id)


async def profile_playlist(
    session: AsyncSession,
    username: str,
    playlist_id: UUID,
    request: PeoplePageRequest,
    *,
    viewer_id: UUID,
) -> ProfilePlaylistSongs:
    async with session.begin():
        return await people_actions.profile_playlist(
            session,
            username,
            playlist_id,
            viewer_id=viewer_id,
            page=request.page,
        )


async def connections(
    session: AsyncSession,
    username: str,
    request: PeoplePageRequest,
    *,
    viewer_id: UUID,
    followers: bool,
) -> Page[Person]:
    async with session.begin():
        return await people_actions.connections(
            session,
            username,
            viewer_id=viewer_id,
            followers=followers,
            page=request.page,
            page_size=request.page_size,
        )


async def follow(
    session: AsyncSession,
    redis: Redis,
    username: str,
    *,
    viewer_id: UUID,
    now: datetime,
) -> tuple[FollowStates, UUID | None]:
    async with session.begin():
        return await people_actions.follow(
            session,
            redis,
            username,
            viewer_id=viewer_id,
            now=now,
        )


async def unfollow(session: AsyncSession, username: str, *, viewer_id: UUID) -> None:
    async with session.begin():
        await people_actions.unfollow(session, username, viewer_id=viewer_id)


async def remove_follower(
    session: AsyncSession,
    username: str,
    *,
    viewer_id: UUID,
) -> None:
    async with session.begin():
        await people_actions.remove_follower(session, username, viewer_id=viewer_id)


async def requests(
    session: AsyncSession,
    request: PeoplePageRequest,
    *,
    viewer_id: UUID,
) -> Page[Person]:
    async with session.begin():
        return await people_actions.requests(
            session,
            viewer_id=viewer_id,
            page=request.page,
            page_size=request.page_size,
        )


async def answer_request(
    session: AsyncSession,
    username: str,
    *,
    viewer_id: UUID,
    accept: bool,
    now: datetime,
) -> UUID | None:
    async with session.begin():
        return await people_actions.answer_request(
            session,
            username,
            viewer_id=viewer_id,
            accept=accept,
            now=now,
        )


async def set_blocked(
    session: AsyncSession,
    username: str,
    *,
    viewer_id: UUID,
    blocked: bool,
) -> UUID:
    async with session.begin():
        return await people_actions.set_blocked(
            session,
            username,
            viewer_id=viewer_id,
            blocked=blocked,
        )


async def report(session: AsyncSession, username: str, *, viewer_id: UUID) -> None:
    async with session.begin():
        await people_actions.report(session, username, viewer_id=viewer_id)


async def set_on_profile(
    session: AsyncSession,
    playlist_id: UUID,
    *,
    viewer_id: UUID,
    on_profile: bool,
) -> None:
    async with session.begin():
        await people_actions.set_on_profile(
            session,
            playlist_id,
            viewer_id=viewer_id,
            on_profile=on_profile,
        )
