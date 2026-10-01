import hashlib
import secrets
from datetime import datetime
from datetime import timedelta
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories import auth as auth_repositories
from src.settings import settings
from src.structs.enums import CacheKeys


def token_hash(
    token: str,
) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def cached_user_id(
    redis: Redis,
    token: str,
) -> UUID | None:
    try:
        user_id = await redis.get(
            CacheKeys.AUTH_SESSION.format(token=token_hash(token))
        )
    except RedisError:
        return None

    return UUID(str(user_id)) if user_id else None


async def _cache(
    redis: Redis,
    hashed: str,
    user_id: UUID,
    *,
    seconds: int,
) -> None:
    try:
        await redis.set(
            CacheKeys.AUTH_SESSION.format(token=hashed),
            str(user_id),
            ex=seconds,
        )
    except RedisError:
        return


async def start_session(
    session: AsyncSession,
    redis: Redis,
    *,
    user_id: UUID,
    now: datetime,
    ip: str | None,
    user_agent: str | None,
) -> str:
    token = secrets.token_urlsafe(32)
    hashed = token_hash(token)

    await auth_repositories.create_session(
        session,
        user_id=user_id,
        token_hash=hashed,
        expires_at=now + timedelta(days=settings.auth.session_days),
        now=now,
        ip=ip,
        user_agent=(user_agent or "")[:512] or None,
    )
    await _cache(
        redis,
        hashed,
        user_id,
        seconds=settings.auth.session_cache_seconds,
    )

    return token


async def resolve_session(
    session: AsyncSession,
    redis: Redis,
    token: str,
    *,
    now: datetime,
) -> UUID | None:
    auth = settings.auth

    if (user_id := await cached_user_id(redis, token)) is not None:
        return user_id

    hashed = token_hash(token)
    async with session.begin():
        live = await auth_repositories.get_live_session(
            session,
            hashed,
            now=now,
        )
        if live is None:
            return None

        if live.last_seen_at < now - timedelta(hours=auth.session_refresh_hours):
            await auth_repositories.extend_session(
                session,
                live.id,
                expires_at=now + timedelta(days=auth.session_days),
                now=now,
            )

        user_id, expires_at = live.user_id, live.expires_at

    left = int((expires_at - now).total_seconds())
    await _cache(
        redis,
        hashed,
        live.user_id,
        seconds=max(1, min(auth.session_cache_seconds, left)),
    )

    return user_id


async def end_session(
    session: AsyncSession,
    redis: Redis,
    token: str,
) -> None:
    hashed = token_hash(token)
    async with session.begin():
        await auth_repositories.delete_session(session, hashed)

    try:
        await redis.delete(CacheKeys.AUTH_SESSION.format(token=hashed))
    except RedisError:
        return
