from datetime import datetime
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.actions import rate_limit as rate_limit_actions
from src.actions import shares as shares_actions
from src.exceptions import ForbiddenError
from src.exceptions import NotFoundError
from src.exceptions import TooManyRequestsError
from src.repositories import catalog as catalog_repositories
from src.repositories import messages as messages_repositories
from src.repositories import people as people_repositories
from src.settings import settings
from src.structs.models.requests import SendMessageRequest
from src.structs.models.responses import ChatMessage
from src.structs.models.responses import Conversation
from src.structs.models.responses import ConversationSummary
from src.structs.models.responses import MessagePerson


MINUTE = 60
DAY = 24 * 60 * 60
PEOPLE_SEARCHES_PER_MINUTE = 60
PEOPLE_RESULTS = 20
REACTIONS_PER_MINUTE = 60


async def _summary(
    session: AsyncSession,
    conversation_id: UUID,
    user_id: UUID,
) -> ConversationSummary:
    summary = await messages_repositories.get_summary(session, conversation_id, user_id)
    if summary is None:
        raise NotFoundError("This chat does not exist")

    return summary


async def _limit(redis: Redis, user_id: UUID) -> None:
    limits = settings.messages
    for key, limit, seconds in (
        (f"messages-minute:{user_id}", limits.per_minute, MINUTE),
        (f"messages-day:{user_id}", limits.per_day, DAY),
    ):
        result = await rate_limit_actions.hit(
            redis,
            key,
            limit=limit,
            window_seconds=seconds,
        )
        if not result.allowed:
            raise TooManyRequestsError(
                "You have sent a lot of messages, try again later",
                retry_after_seconds=result.reset,
            )


async def read_conversation(
    session: AsyncSession,
    conversation_id: UUID,
    user_id: UUID,
    *,
    before: UUID | None,
    limit: int,
) -> Conversation:
    summary = await _summary(session, conversation_id, user_id)
    messages, more = await messages_repositories.list_messages(
        session,
        conversation_id,
        user_id,
        before=before,
        limit=limit,
    )

    return Conversation(**summary.model_dump(), messages=messages, more=more)


async def send_message(
    session: AsyncSession,
    redis: Redis,
    conversation_id: UUID,
    request: SendMessageRequest,
    *,
    user_id: UUID,
    now: datetime,
) -> tuple[ChatMessage, list[UUID]]:
    summary = await _summary(session, conversation_id, user_id)
    if not summary.can_send:
        raise ForbiddenError("You can't message this person")
    await _limit(redis, user_id)
    if request.track_id is not None and not await catalog_repositories.track_exists(
        session,
        request.track_id,
    ):
        raise NotFoundError("The track does not exist")
    share_id = None
    if request.playlist_id is not None:
        share_id, _ = await shares_actions.share_playlist(
            session,
            redis,
            request.playlist_id,
            user_id=user_id,
        )

    sent = await messages_repositories.add_message(
        session,
        conversation_id,
        user_id,
        text=request.text,
        track_id=request.track_id,
        share_id=share_id,
        now=now,
    )

    return sent, await messages_repositories.members(session, conversation_id)


async def message_people(
    session: AsyncSession,
    redis: Redis,
    query: str,
    *,
    user_id: UUID,
) -> list[MessagePerson]:
    result = await rate_limit_actions.hit(
        redis,
        f"message-people:{user_id}",
        limit=PEOPLE_SEARCHES_PER_MINUTE,
        window_seconds=MINUTE,
    )
    if not result.allowed:
        raise TooManyRequestsError(
            "Too many of those for now, try again later",
            retry_after_seconds=result.reset,
        )

    return await messages_repositories.message_people(
        session,
        user_id,
        query,
        limit=PEOPLE_RESULTS,
    )


async def send_to(
    session: AsyncSession,
    redis: Redis,
    username: str,
    request: SendMessageRequest,
    *,
    user_id: UUID,
    now: datetime,
) -> tuple[UUID, ChatMessage, list[UUID]]:
    other = await people_repositories.by_username(session, username)
    if (
        other is None
        or other.id == user_id
        or await people_repositories.blocked_either(session, user_id, other.id)
    ):
        raise NotFoundError("Nobody has that username")

    conversation_id = await messages_repositories.conversation_between(
        session,
        user_id,
        other.id,
    )
    if conversation_id is None:
        if not await people_repositories.follows_each_other(
            session,
            user_id,
            other.id,
        ):
            raise ForbiddenError("You can message people who follow you back")

        conversation_id = await messages_repositories.ensure_conversation(
            session,
            user_id,
            other.id,
        )

    sent, members = await send_message(
        session,
        redis,
        conversation_id,
        request,
        user_id=user_id,
        now=now,
    )

    return conversation_id, sent, members


async def mark_read(
    session: AsyncSession,
    conversation_id: UUID,
    *,
    user_id: UUID,
    now: datetime,
) -> None:
    await _summary(session, conversation_id, user_id)
    await messages_repositories.mark_read(session, conversation_id, user_id, now=now)


async def unsend(
    session: AsyncSession,
    conversation_id: UUID,
    message_id: UUID,
    *,
    user_id: UUID,
    now: datetime,
) -> list[UUID]:
    await _summary(session, conversation_id, user_id)
    if not await messages_repositories.unsend(
        session,
        conversation_id,
        message_id,
        user_id,
        now=now,
    ):
        raise NotFoundError("This message can't be unsent")

    return await messages_repositories.members(session, conversation_id)


async def react(
    session: AsyncSession,
    redis: Redis,
    conversation_id: UUID,
    message_id: UUID,
    *,
    user_id: UUID,
    emoji: str | None,
) -> tuple[list[UUID], UUID | None]:
    summary = await _summary(session, conversation_id, user_id)
    if not summary.can_send:
        raise ForbiddenError("You can't react in this chat")

    result = await rate_limit_actions.hit(
        redis,
        f"reactions:{user_id}",
        limit=REACTIONS_PER_MINUTE,
        window_seconds=MINUTE,
    )
    if not result.allowed:
        raise TooManyRequestsError(
            "You have reacted a lot, try again later",
            retry_after_seconds=result.reset,
        )

    reacted = await messages_repositories.react(
        session,
        conversation_id,
        message_id,
        user_id,
        emoji=emoji,
    )
    if reacted is None:
        raise NotFoundError("This message can't be reacted to")

    sender_id, changed = reacted
    if not changed:
        return [], None

    members = await messages_repositories.members(session, conversation_id)

    return members, sender_id if emoji and sender_id != user_id else None


async def set_blocked(
    session: AsyncSession,
    conversation_id: UUID,
    *,
    user_id: UUID,
    blocked: bool,
) -> list[UUID]:
    await _summary(session, conversation_id, user_id)
    other = await messages_repositories.other_member(session, conversation_id, user_id)
    if other is None:
        raise NotFoundError("This person no longer has an account")

    if blocked:
        await people_repositories.block_user(session, user_id, other)
    else:
        await people_repositories.unblock_user(session, user_id, other)

    await messages_repositories.touch_conversation(session, user_id, other)

    return [user_id, other]


async def report_message(
    session: AsyncSession,
    message_id: UUID,
    *,
    user_id: UUID,
) -> None:
    if not await messages_repositories.report_message(session, user_id, message_id):
        raise NotFoundError("This message can't be reported")
