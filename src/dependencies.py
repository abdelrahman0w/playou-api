from collections.abc import AsyncGenerator
from datetime import UTC
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi import Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.actions import auth as auth_actions
from src.exceptions import ForbiddenError
from src.exceptions import UnauthorizedError
from src.providers import DatabaseSessions
from src.providers import RedisConnection
from src.services import OAuthPlatform
from src.services import ResendConnection
from src.services import ResendService
from src.services import available_platforms
from src.settings import settings
from src.structs.enums import Platforms
from src.utils import resolve_client_ip


async def get_db_session() -> AsyncGenerator[AsyncSession]:
    async with DatabaseSessions.get()() as session:
        yield session


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return DatabaseSessions.get()


def get_redis() -> Redis:
    return RedisConnection.get()


def get_now() -> datetime:
    return datetime.now(UTC)


def get_client_ip(request: Request) -> str | None:
    return resolve_client_ip(
        request.client.host if request.client else None,
        request.headers.get(settings.rate_limit.client_ip_header),
    )


def get_session_token(request: Request) -> str | None:
    if token := request.cookies.get(settings.auth.cookie_name):
        return token

    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and (token := token.strip()):
        return token

    return None


def get_resend() -> ResendService | None:
    return ResendConnection.get()


def get_platforms() -> dict[Platforms, OAuthPlatform]:
    return available_platforms()


DBSessionDep = Annotated[AsyncSession, Depends(get_db_session)]
SessionFactoryDep = Annotated[
    async_sessionmaker[AsyncSession],
    Depends(get_session_factory),
]
RedisDep = Annotated[Redis, Depends(get_redis)]
NowDep = Annotated[datetime, Depends(get_now)]
ResendDep = Annotated[ResendService | None, Depends(get_resend)]
ClientIPDep = Annotated[str | None, Depends(get_client_ip)]
PlatformsDep = Annotated[dict[Platforms, OAuthPlatform], Depends(get_platforms)]


async def get_user_id(
    request: Request,
    session: DBSessionDep,
    redis: RedisDep,
    now: NowDep,
) -> UUID | None:
    token = get_session_token(request)
    if not token:
        return None

    return await auth_actions.resolve_session(
        session,
        redis,
        token,
        now=now,
    )


async def require_user_id(
    user_id: Annotated[UUID | None, Depends(get_user_id)],
) -> UUID:
    if user_id is None:
        raise UnauthorizedError("Sign in to continue")

    return user_id


def require_trusted_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin is not None and origin not in settings.cors.origins:
        raise ForbiddenError("This origin may not do that")


OptionalUserIDDep = Annotated[UUID | None, Depends(get_user_id)]
UserIDDep = Annotated[UUID, Depends(require_user_id)]
