from datetime import datetime
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.actions import auth as auth_actions
from src.actions import library as library_actions
from src.exceptions import UnauthorizedError
from src.repositories import auth as auth_repositories
from src.repositories import people as people_repositories
from src.services import ResendService
from src.settings import settings
from src.structs.models.requests import EmailCodeRequest
from src.structs.models.requests import EmailVerifyRequest
from src.structs.models.requests import NameRequest
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
        name=request.name,
        username=request.username,
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
        described = await _described(session, user, now=now)

    return described, token


async def _described(
    session: AsyncSession,
    user: AuthUser,
    *,
    now: datetime,
) -> AuthUser:
    limited = await auth_actions.with_name_limits(session, user, now=now)
    followers, following = await people_repositories.counts(session, user.id)
    limited = limited.model_copy(
        update={"followers": followers, "following": following}
    )

    return limited.model_copy(
        update={
            "can_delete_data": settings.data.deletion_enabled,
            "lyrics_enabled": settings.lyrics.enabled,
        },
    )


async def get_me(
    session: AsyncSession,
    user_id: UUID,
    *,
    now: datetime,
) -> AuthUser:
    async with session.begin():
        user = await auth_repositories.get_user(session, user_id)
        if user is None:
            raise UnauthorizedError(
                "Sign in to continue",
            )

        return await _described(session, user, now=now)


async def update_me(
    session: AsyncSession,
    user_id: UUID,
    request: NameRequest,
    *,
    now: datetime,
) -> AuthUser:
    async with session.begin():
        if request.name is not None:
            await auth_actions.change_name(session, user_id, request.name, now=now)
        if request.username is not None:
            await auth_actions.change_username(
                session,
                user_id,
                request.username,
                now=now,
            )

        values: dict[str, object] = {}
        if request.searchable is not None:
            values["searchable"] = request.searchable
        if request.private is not None:
            values["private"] = request.private
            if not request.private:
                await people_repositories.accept_all(session, user_id, now=now)
        if values:
            await auth_repositories.update_user(session, user_id, **values)

        user = await auth_repositories.get_user(session, user_id)
        if user is None:
            raise UnauthorizedError("Sign in to continue")

        return await _described(session, user, now=now)


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
