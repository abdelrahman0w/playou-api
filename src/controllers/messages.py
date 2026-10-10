import asyncio
import contextlib
from datetime import datetime
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.actions import messages as messages_actions
from src.exceptions import UnsupportedError
from src.repositories import messages as messages_repositories
from src.settings import settings
from src.structs.models import Page
from src.structs.models.requests import ConversationListRequest
from src.structs.models.requests import MessageListRequest
from src.structs.models.requests import PushRemovalRequest
from src.structs.models.requests import PushSubscriptionRequest
from src.structs.models.requests import SendMessageRequest
from src.structs.models.responses import ChatMessage
from src.structs.models.responses import Conversation
from src.structs.models.responses import ConversationSummary
from src.structs.models.responses import MessageUpdates
from src.structs.models.responses import PushSettings


async def list_conversations(
    session: AsyncSession,
    request: ConversationListRequest,
    *,
    user_id: UUID,
) -> Page[ConversationSummary]:
    async with session.begin():
        return await messages_repositories.list_conversations(
            session,
            user_id,
            with_messages=request.with_messages,
            page=request.page,
            page_size=request.page_size,
        )


async def read_conversation(
    session: AsyncSession,
    conversation_id: UUID,
    request: MessageListRequest,
    *,
    user_id: UUID,
) -> Conversation:
    async with session.begin():
        return await messages_actions.read_conversation(
            session,
            conversation_id,
            user_id,
            before=request.before,
            limit=request.limit,
        )


async def send_message(
    session: AsyncSession,
    redis: Redis,
    conversation_id: UUID,
    request: SendMessageRequest,
    *,
    user_id: UUID,
    now: datetime,
) -> tuple[ChatMessage, list[UUID]]:
    async with session.begin():
        sent, members = await messages_actions.send_message(
            session,
            redis,
            conversation_id,
            request,
            user_id=user_id,
            now=now,
        )
    await messages_actions.announce(redis, members)

    return sent, members


async def notify(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    conversation_id: UUID,
    message: ChatMessage,
    *,
    sender_id: UUID,
    members: list[UUID],
) -> None:
    await messages_actions.notify(
        session_factory,
        redis,
        conversation_id,
        message,
        sender_id=sender_id,
        members=members,
    )


def push_settings() -> PushSettings:
    messages = settings.messages

    return PushSettings(
        enabled=messages.push_enabled,
        public_key=messages.push_public_key if messages.push_enabled else None,
    )


async def subscribe(
    session: AsyncSession,
    request: PushSubscriptionRequest,
    *,
    user_id: UUID,
) -> None:
    if not settings.messages.push_enabled:
        raise UnsupportedError("Notifications are turned off")

    async with session.begin():
        await messages_repositories.save_subscription(
            session,
            user_id,
            endpoint=request.endpoint,
            p256dh=request.keys.p256dh,
            auth=request.keys.auth,
        )


async def unsubscribe(
    session: AsyncSession,
    request: PushRemovalRequest,
    *,
    user_id: UUID,
) -> None:
    async with session.begin():
        await messages_repositories.delete_subscription(
            session,
            user_id,
            request.endpoint,
        )


async def mark_read(
    session: AsyncSession,
    redis: Redis,
    conversation_id: UUID,
    *,
    user_id: UUID,
    now: datetime,
) -> None:
    async with session.begin():
        await messages_actions.mark_read(
            session,
            conversation_id,
            user_id=user_id,
            now=now,
        )
    await messages_actions.announce(redis, [user_id])


async def unsend(
    session: AsyncSession,
    redis: Redis,
    conversation_id: UUID,
    message_id: UUID,
    *,
    user_id: UUID,
    now: datetime,
) -> None:
    async with session.begin():
        members = await messages_actions.unsend(
            session,
            conversation_id,
            message_id,
            user_id=user_id,
            now=now,
        )
    await messages_actions.announce(redis, members)


async def set_blocked(
    session: AsyncSession,
    redis: Redis,
    conversation_id: UUID,
    *,
    user_id: UUID,
    blocked: bool,
    now: datetime,
) -> None:
    async with session.begin():
        members = await messages_actions.set_blocked(
            session,
            conversation_id,
            user_id=user_id,
            blocked=blocked,
            now=now,
        )
    await messages_actions.announce(redis, members)


async def report_message(
    session: AsyncSession,
    message_id: UUID,
    *,
    user_id: UUID,
) -> None:
    async with session.begin():
        await messages_actions.report_message(session, message_id, user_id=user_id)


async def _updates(session: AsyncSession, user_id: UUID) -> MessageUpdates:
    async with session.begin():
        tag, unread = await messages_repositories.updates(session, user_id)

    return MessageUpdates(tag=tag, unread=unread)


async def updates(
    session: AsyncSession,
    redis: Redis,
    changes: messages_actions.MessageChanges,
    *,
    user_id: UUID,
    seen: str | None,
    wait: int,
    viewing: UUID | None,
) -> MessageUpdates:
    if viewing is not None:
        await messages_actions.watch_viewing(redis, user_id, viewing, seconds=wait)
    if wait <= 0:
        return await _updates(session, user_id)

    with changes.watch(user_id) as changed:
        read = await _updates(session, user_id)
        if read.tag != seen:
            return read

        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(changed.wait(), timeout=wait)
        if not changed.is_set():
            return read

    return await _updates(session, user_id)
