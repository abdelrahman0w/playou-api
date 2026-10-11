from datetime import datetime
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.actions import rate_limit as rate_limit_actions
from src.exceptions import ForbiddenError
from src.exceptions import NotFoundError
from src.exceptions import TooManyRequestsError
from src.repositories import messages as messages_repositories
from src.repositories import people as people_repositories
from src.structs import tables
from src.structs.enums import FollowStates
from src.structs.models import Page
from src.structs.models.responses import Person
from src.structs.models.responses import Profile
from src.structs.models.responses import ProfilePlaylistSongs
from src.structs.models.responses import UsernameCheck
from src.utils.client_ip import client_key
from src.utils.usernames import InvalidUsernameError
from src.utils.usernames import clean_username


MINUTE = 60
DAY = 24 * 60 * 60
SEARCHES_PER_MINUTE = 60
CHECKS_PER_MINUTE = 60
SIGNED_OUT_CHECKS_PER_MINUTE = 30
FOLLOWS_PER_DAY = 100
SEARCH_RESULTS = 20
PLAYLIST_PAGE = 100


async def _limit(redis: Redis, key: str, *, limit: int, seconds: int) -> None:
    result = await rate_limit_actions.hit(
        redis,
        key,
        limit=limit,
        window_seconds=seconds,
    )
    if not result.allowed:
        raise TooManyRequestsError(
            "Too many of those for now, try again later",
            retry_after_seconds=result.reset,
        )


async def _person(
    session: AsyncSession,
    viewer_id: UUID,
    username: str,
    *,
    blocked_too: bool = False,
) -> tables.User:
    user = await people_repositories.by_username(session, username)
    if user is None:
        raise NotFoundError("Nobody has that username")
    if user.id != viewer_id and await people_repositories.blocked_either(
        session,
        viewer_id,
        user.id,
    ):
        if blocked_too and await people_repositories.has_blocked(
            session,
            viewer_id,
            user.id,
        ):
            return user
        raise NotFoundError("Nobody has that username")

    return user


async def _sees(session: AsyncSession, viewer_id: UUID, user: tables.User) -> bool:
    return (
        not user.private
        or user.id == viewer_id
        or await people_repositories.is_following(session, viewer_id, user.id)
    )


async def search(
    session: AsyncSession,
    redis: Redis,
    query: str,
    *,
    viewer_id: UUID,
) -> list[Person]:
    await _limit(
        redis,
        f"people-search:{viewer_id}",
        limit=SEARCHES_PER_MINUTE,
        seconds=MINUTE,
    )

    return await people_repositories.search(
        session,
        viewer_id,
        query,
        limit=SEARCH_RESULTS,
    )


async def check_username(
    session: AsyncSession,
    redis: Redis,
    username: str,
    *,
    viewer_id: UUID | None,
    ip: str | None,
) -> UsernameCheck:
    if viewer_id is not None:
        await _limit(
            redis,
            f"username-checks:user:{viewer_id}",
            limit=CHECKS_PER_MINUTE,
            seconds=MINUTE,
        )
    elif ip is not None:
        await _limit(
            redis,
            f"username-checks:ip:{client_key(ip)}",
            limit=SIGNED_OUT_CHECKS_PER_MINUTE,
            seconds=MINUTE,
        )
    try:
        cleaned = clean_username(username)
    except InvalidUsernameError as exc:
        return UsernameCheck(username=username, available=False, reason=str(exc))

    taken = await people_repositories.username_taken(
        session,
        cleaned,
        except_user=viewer_id,
    )

    return UsernameCheck(
        username=cleaned,
        available=not taken,
        reason="That username is taken" if taken else None,
    )


async def profile(session: AsyncSession, username: str, *, viewer_id: UUID) -> Profile:
    user = await _person(session, viewer_id, username, blocked_too=True)
    (person,) = await people_repositories.people(session, viewer_id, [user])
    followers, following = await people_repositories.counts(session, user.id)
    blocked = user.id != viewer_id and await people_repositories.has_blocked(
        session,
        viewer_id,
        user.id,
    )
    visible = not blocked and await _sees(session, viewer_id, user)
    chat_id = None
    can_message = False
    if not blocked and user.id != viewer_id:
        chat_id = await messages_repositories.conversation_between(
            session,
            viewer_id,
            user.id,
        )
        can_message = (
            chat_id is not None
            or await people_repositories.follows_each_other(
                session,
                viewer_id,
                user.id,
            )
        )

    return Profile(
        **person.model_dump(),
        followers=followers,
        following=following,
        you=user.id == viewer_id,
        blocked=blocked,
        visible=visible,
        chat_id=chat_id,
        can_message=can_message,
        playlists=(
            await people_repositories.profile_playlists(session, user.id)
            if visible
            else []
        ),
    )


async def profile_playlist(
    session: AsyncSession,
    username: str,
    playlist_id: UUID,
    *,
    viewer_id: UUID,
    page: int,
) -> ProfilePlaylistSongs:
    user = await _person(session, viewer_id, username)
    if not await _sees(session, viewer_id, user):
        raise NotFoundError("This playlist is not on their profile")
    playlist = await people_repositories.profile_playlist(session, user.id, playlist_id)
    if playlist is None:
        raise NotFoundError("This playlist is not on their profile")

    items, more = await people_repositories.playlist_songs(
        session,
        playlist_id,
        page=page,
        page_size=PLAYLIST_PAGE,
    )

    return ProfilePlaylistSongs(playlist=playlist, items=items, more=more)


async def connections(
    session: AsyncSession,
    username: str,
    *,
    viewer_id: UUID,
    followers: bool,
    page: int,
    page_size: int,
) -> Page[Person]:
    user = await _person(session, viewer_id, username)
    if not await _sees(session, viewer_id, user):
        raise ForbiddenError("This profile is private")

    listing = (
        people_repositories.followers if followers else people_repositories.following
    )

    return await listing(
        session,
        viewer_id,
        user.id,
        page=page,
        page_size=page_size,
    )


async def follow(
    session: AsyncSession,
    redis: Redis,
    username: str,
    *,
    viewer_id: UUID,
    now: datetime,
) -> tuple[FollowStates, UUID | None]:
    user = await _person(session, viewer_id, username)
    if user.id == viewer_id:
        raise ForbiddenError("You can't follow yourself")

    await _limit(
        redis,
        f"follows:{viewer_id}",
        limit=FOLLOWS_PER_DAY,
        seconds=DAY,
    )
    created = await people_repositories.follow(
        session,
        viewer_id,
        user.id,
        accepted_at=None if user.private else now,
    )
    state = FollowStates.REQUESTED if user.private else FollowStates.FOLLOWING
    if not created:
        state = (
            FollowStates.FOLLOWING
            if await people_repositories.is_following(session, viewer_id, user.id)
            else FollowStates.REQUESTED
        )

    return state, user.id if created else None


async def unfollow(
    session: AsyncSession,
    username: str,
    *,
    viewer_id: UUID,
) -> None:
    user = await _person(session, viewer_id, username)
    await people_repositories.unfollow(session, viewer_id, user.id)


async def remove_follower(
    session: AsyncSession,
    username: str,
    *,
    viewer_id: UUID,
) -> None:
    user = await _person(session, viewer_id, username)
    await people_repositories.unfollow(session, user.id, viewer_id)


async def requests(
    session: AsyncSession,
    *,
    viewer_id: UUID,
    page: int,
    page_size: int,
) -> Page[Person]:
    return await people_repositories.requests(
        session,
        viewer_id,
        page=page,
        page_size=page_size,
    )


async def answer_request(
    session: AsyncSession,
    username: str,
    *,
    viewer_id: UUID,
    accept: bool,
    now: datetime,
) -> UUID | None:
    user = await _person(session, viewer_id, username)
    if not accept:
        await people_repositories.unfollow(session, user.id, viewer_id)

        return None

    if not await people_repositories.accept(session, user.id, viewer_id, now=now):
        raise NotFoundError("There's no request from them")

    return user.id


async def set_blocked(
    session: AsyncSession,
    username: str,
    *,
    viewer_id: UUID,
    blocked: bool,
) -> UUID:
    user = await _person(session, viewer_id, username, blocked_too=True)
    if user.id == viewer_id:
        raise ForbiddenError("You can't block yourself")

    if blocked:
        await people_repositories.block_user(session, viewer_id, user.id)
    else:
        await people_repositories.unblock_user(session, viewer_id, user.id)
    await messages_repositories.touch_conversation(session, viewer_id, user.id)

    return user.id


async def report(session: AsyncSession, username: str, *, viewer_id: UUID) -> None:
    user = await _person(session, viewer_id, username, blocked_too=True)
    if user.id == viewer_id:
        raise ForbiddenError("You can't report yourself")

    await people_repositories.report_user(session, viewer_id, user.id)


async def set_on_profile(
    session: AsyncSession,
    playlist_id: UUID,
    *,
    viewer_id: UUID,
    on_profile: bool,
) -> None:
    if not await people_repositories.set_on_profile(
        session,
        viewer_id,
        playlist_id,
        on_profile=on_profile,
    ):
        raise NotFoundError("Only a playlist you own can be on your profile")
