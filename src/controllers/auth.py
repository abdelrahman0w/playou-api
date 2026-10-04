from datetime import datetime
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.actions import auth as auth_actions
from src.actions import library as library_actions
from src.exceptions import UnauthorizedError
from src.repositories import auth as auth_repositories
from src.services import ResendService
from src.settings import settings
from src.structs.models.requests import EmailCodeRequest
from src.structs.models.requests import EmailVerifyRequest
from src.structs.models.responses import AuthUser
from src.structs.models.responses import EmailCodeSent


async def send_email_code(
    session: AsyncSession,
    redis: Redis,
    resend: ResendService | None,
    request: EmailCodeRequest,
    *,
    ip: str | None,
    now: datetime,
) -> EmailCodeSent:
    return await auth_actions.send_email_code(
        session,
        redis,
        resend,
        email=request.email,
        locale=request.locale,
        ip=ip,
        now=now,
    )


async def verify_email_code(
    session: AsyncSession,
    redis: Redis,
    request: EmailVerifyRequest,
    *,
    ip: str | None,
    user_agent: str | None,
    now: datetime,
) -> tuple[AuthUser, str]:
    user, _ = await auth_actions.verify_email_code(
        session,
        redis=redis,
        email=request.email,
        code=request.code,
        locale=request.locale,
        ip=ip,
        now=now,
    )

    async with session.begin():
        token = await auth_actions.start_session(
            session,
            redis,
            user_id=user.id,
            now=now,
            ip=ip,
            user_agent=user_agent,
        )

    return _with_permissions(user), token


def _with_permissions(user: AuthUser) -> AuthUser:
    return user.model_copy(
        update={"can_delete_data": settings.data.deletion_enabled},
    )


async def get_me(
    session: AsyncSession,
    user_id: UUID,
) -> AuthUser:
    user = await auth_repositories.get_user(session, user_id)
    if user is None:
        raise UnauthorizedError(
            "Sign in to continue",
        )

    return _with_permissions(user)


async def sign_out(
    session: AsyncSession,
    redis: Redis,
    token: str | None,
) -> None:
    if token:
        await auth_actions.end_session(session, redis, token)


async def delete_me(
    session: AsyncSession,
    redis: Redis,
    user_id: UUID,
) -> None:
    library_actions.ensure_allowed()
    async with session.begin():
        await library_actions.delete_user(session, redis, user_id)
