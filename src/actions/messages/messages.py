from datetime import datetime
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.actions import rate_limit as rate_limit_actions
from src.exceptions import ForbiddenError
from src.exceptions import NotFoundError
from src.exceptions import TooManyRequestsError
from src.repositories import catalog as catalog_repositories
from src.repositories import messages as messages_repositories
from src.settings import settings
from src.structs.models.requests import SendMessageRequest
from src.structs.models.responses import ChatMessage
from src.structs.models.responses import Conversation
from src.structs.models.responses import ConversationSummary


MINUTE = 60
DAY = 24 * 60 * 60


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

    sent = await messages_repositories.add_message(
        session,
        conversation_id,
        user_id,
        text=request.text,
        track_id=request.track_id,
        now=now,
    )

    return sent, await messages_repositories.members(session, conversation_id)


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


async def set_blocked(
    session: AsyncSession,
    conversation_id: UUID,
    *,
    user_id: UUID,
    blocked: bool,
    now: datetime,
) -> list[UUID]:
    await _summary(session, conversation_id, user_id)
    await messages_repositories.set_blocked(
        session,
        conversation_id,
        user_id,
        blocked_at=now if blocked else None,
    )

    return await messages_repositories.members(session, conversation_id)


async def report_message(
    session: AsyncSession,
    message_id: UUID,
    *,
    user_id: UUID,
) -> None:
    if not await messages_repositories.report_message(session, user_id, message_id):
        raise NotFoundError("This message can't be reported")
