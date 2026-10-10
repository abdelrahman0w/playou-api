import hashlib
import secrets
from dataclasses import dataclass
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


@dataclass(frozen=True)
class SessionUser:
    user_id: UUID


async def cached_session(
    redis: Redis,
    token: str,
) -> SessionUser | None:
    try:
        cached = await redis.get(CacheKeys.AUTH_SESSION.format(token=token_hash(token)))
    except RedisError:
        return None
    if not cached:
        return None

    return SessionUser(user_id=UUID(str(cached)))


async def _cache(
    redis: Redis,
    hashed: str,
    user: SessionUser,
    *,
    seconds: int,
) -> None:
    try:
        await redis.set(
            CacheKeys.AUTH_SESSION.format(token=hashed),
            str(user.user_id),
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
        SessionUser(user_id=user_id),
        seconds=settings.auth.session_cache_seconds,
    )

    return token


async def resolve_session(
    session: AsyncSession,
    redis: Redis,
    token: str,
    *,
    now: datetime,
    check_cache: bool = True,
) -> SessionUser | None:
    auth = settings.auth

    if check_cache and (cached := await cached_session(redis, token)) is not None:
        return cached

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

        user = SessionUser(user_id=live.user_id)
        expires_at = live.expires_at

    left = int((expires_at - now).total_seconds())
    await _cache(
        redis,
        hashed,
        user,
        seconds=max(1, min(auth.session_cache_seconds, left)),
    )

    return user


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
