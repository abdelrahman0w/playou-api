import json
from collections.abc import Callable
from uuid import UUID

from pywebpush import WebPushException
from pywebpush import webpush_async
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.providers import logger
from src.repositories import messages as messages_repositories
from src.settings import settings
from src.structs import tables
from src.structs.enums import CacheKeys
from src.structs.models.responses import ChatMessage


GONE = frozenset({404, 410})
BASE_LOCALE = "en"
VIEWING_GRACE_SECONDS = 10


async def watch_viewing(
    redis: Redis,
    user_id: UUID,
    conversation_id: UUID,
    *,
    seconds: int,
) -> None:
    try:
        await redis.set(
            CacheKeys.MESSAGES_VIEWING.format(
                user_id=user_id,
                conversation_id=conversation_id,
            ),
            1,
            ex=seconds + VIEWING_GRACE_SECONDS,
        )
    except RedisError:
        return


async def _viewing(redis: Redis, user_id: UUID, conversation_id: UUID) -> bool:
    try:
        return bool(
            await redis.exists(
                CacheKeys.MESSAGES_VIEWING.format(
                    user_id=user_id,
                    conversation_id=conversation_id,
                ),
            ),
        )
    except RedisError:
        return False


def _body(message: ChatMessage) -> str:
    if message.track is not None:
        song = f"🎵 {message.track.title}"

        return f"{song} · {message.text}" if message.text else song

    return message.text or ""


async def _push(subscription: tables.PushSubscription, payload: str) -> bool:
    messages = settings.messages
    private = messages.push_private_key
    key = private.get_secret_value() if private else None
    try:
        await webpush_async(
            {
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
            },
            data=payload,
            vapid_private_key=key,
            vapid_claims={"sub": messages.push_contact},
            ttl=24 * 60 * 60,
            timeout=messages.push_timeout_seconds,
        )
    except WebPushException as exc:
        if exc.status_code in GONE:
            return False
        logger.warning("[Messages] Push Failed", status=exc.status_code)
    except Exception as exc:
        logger.warning("[Messages] Push Failed", error=repr(exc))

    return True


async def notify(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    conversation_id: UUID,
    message: ChatMessage,
    *,
    sender_id: UUID,
    members: list[UUID],
) -> None:
    if not settings.messages.push_enabled:
        return

    recipients = [
        user_id
        for user_id in members
        if user_id != sender_id and not await _viewing(redis, user_id, conversation_id)
    ]
    async with session_factory() as session:
        name = await messages_repositories.user_name(session, sender_id)

    def payload(locale: str) -> dict[str, str]:
        return {
            "title": name or "PlaYou",
            "body": _body(message),
            "url": f"{_prefix(locale)}/messages/{conversation_id}",
            "tag": str(conversation_id),
        }

    await push_to(session_factory, recipients, payload)


def _prefix(locale: str) -> str:
    return "" if locale == BASE_LOCALE else f"/{locale}"


async def push_to(
    session_factory: async_sessionmaker[AsyncSession],
    user_ids: list[UUID],
    payload: Callable[[str], dict[str, str]],
) -> None:
    if not settings.messages.push_enabled or not user_ids:
        return

    async with session_factory() as session:
        subscriptions = await messages_repositories.subscriptions_of(session, user_ids)

    gone = [
        subscription.endpoint
        for subscription, locale in subscriptions
        if not await _push(
            subscription, json.dumps(payload(locale), ensure_ascii=False)
        )
    ]
    if gone:
        async with session_factory() as session, session.begin():
            await messages_repositories.forget_endpoints(session, gone)


FOLLOW_TEXTS = {
    "followed": {"en": "followed you", "ar": "بدأ متابعتك"},
    "requested": {"en": "wants to follow you", "ar": "يريد متابعتك"},
    "accepted": {"en": "accepted your follow request", "ar": "قبل طلب متابعتك"},
}


async def notify_follow(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    kind: str,
    actor_id: UUID,
    recipient_id: UUID,
) -> None:
    async with session_factory() as session:
        actor = await session.get(tables.User, actor_id)
    if actor is None:
        return

    username = actor.username
    name = actor.name

    def payload(locale: str) -> dict[str, str]:
        texts = FOLLOW_TEXTS[kind]

        return {
            "title": name,
            "body": texts.get(locale, texts[BASE_LOCALE]),
            "url": f"{_prefix(locale)}/u/{username}",
            "tag": f"follow:{username}",
        }

    await push_to(session_factory, [recipient_id], payload)


REACTION_TEXTS = {
    "en": "reacted {emoji} to your message",
    "ar": "تفاعل بـ {emoji} مع رسالتك",
}


async def notify_reaction(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    conversation_id: UUID,
    message_id: UUID,
    *,
    actor_id: UUID,
    recipient_id: UUID,
    emoji: str,
) -> None:
    if not settings.messages.push_enabled or await _viewing(
        redis,
        recipient_id,
        conversation_id,
    ):
        return

    async with session_factory() as session:
        name = await messages_repositories.user_name(session, actor_id)

    def payload(locale: str) -> dict[str, str]:
        text = REACTION_TEXTS.get(locale, REACTION_TEXTS[BASE_LOCALE])

        return {
            "title": name or "PlaYou",
            "body": text.format(emoji=emoji),
            "url": f"{_prefix(locale)}/messages/{conversation_id}",
            "tag": f"reaction:{message_id}",
        }

    await push_to(session_factory, [recipient_id], payload)
