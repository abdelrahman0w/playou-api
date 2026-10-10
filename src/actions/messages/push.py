import json
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
        subscriptions = await messages_repositories.subscriptions_of(
            session,
            recipients,
        )
        name = await messages_repositories.user_name(session, sender_id)
    if not subscriptions:
        return

    def payload(locale: str) -> str:
        prefix = "" if locale == BASE_LOCALE else f"/{locale}"

        return json.dumps(
            {
                "title": name or "PlaYou",
                "body": _body(message),
                "url": f"{prefix}/messages/{conversation_id}",
                "tag": str(conversation_id),
            },
            ensure_ascii=False,
        )

    gone = [
        subscription.endpoint
        for subscription, locale in subscriptions
        if not await _push(subscription, payload(locale))
    ]
    if gone:
        async with session_factory() as session, session.begin():
            await messages_repositories.forget_endpoints(session, gone)
