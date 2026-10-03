from datetime import datetime
from urllib.parse import urlencode
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.actions import accounts as accounts_actions
from src.exceptions import AppError
from src.exceptions import PlatformNotLinkedError
from src.exceptions import UnauthorizedError
from src.exceptions import UnsupportedError
from src.providers import logger
from src.repositories import accounts as accounts_repositories
from src.services import OAuthPlatform
from src.settings import settings
from src.structs.enums import Platforms
from src.structs.models.requests import PushPreferencesRequest
from src.structs.models.responses import LinkedAccount
from src.structs.models.responses import PushPreferences


def _service(
    platforms: dict[Platforms, OAuthPlatform],
    platform: Platforms,
) -> OAuthPlatform:
    if (service := platforms.get(platform)) is None:
        raise UnsupportedError(f"{platform.title()} is not available")

    return service


def _web_url(**params: str) -> str:
    return f"{settings.app.web_url.rstrip('/')}/accounts?{urlencode(params)}"


async def list_accounts(
    session: AsyncSession,
    platforms: dict[Platforms, OAuthPlatform],
    user_id: UUID,
) -> list[LinkedAccount]:
    async with session.begin():
        accounts = await accounts_repositories.list_accounts(session, user_id)

    return [
        LinkedAccount.from_stored(account, platforms[account.platform].capabilities)
        for account in accounts
        if account.platform in platforms
    ]


async def connect(
    redis: Redis,
    platforms: dict[Platforms, OAuthPlatform],
    platform: Platforms,
    *,
    user_id: UUID,
) -> str:
    return await accounts_actions.start_link(
        redis,
        _service(platforms, platform),
        user_id=user_id,
    )


async def finish_connect(
    session: AsyncSession,
    redis: Redis,
    platforms: dict[Platforms, OAuthPlatform],
    platform: Platforms,
    *,
    user_id: UUID | None,
    code: str | None,
    state: str | None,
    error: str | None,
    now: datetime,
) -> str:
    try:
        if user_id is None:
            raise UnauthorizedError("Sign in to link an account")
        if error is not None or code is None or state is None:
            return _web_url(platform=platform, error=error or "access_denied")

        await accounts_actions.finish_link(
            session,
            redis,
            _service(platforms, platform),
            user_id=user_id,
            code=code,
            state=state,
            now=now,
        )
    except AppError as exc:
        logger.warning(
            "[Accounts] Link Failed",
            platform=platform,
            error_type=exc.error_type,
            error=exc.message,
        )

        return _web_url(platform=platform, error=exc.error_type)

    return _web_url(linked=platform)


async def disconnect(
    session: AsyncSession,
    platform: Platforms,
    *,
    user_id: UUID,
) -> None:
    async with session.begin():
        deleted = await accounts_repositories.delete_account(session, user_id, platform)

    if not deleted:
        raise PlatformNotLinkedError(f"{platform.title()} is not linked")


async def get_preferences(
    session: AsyncSession,
    platform: Platforms,
    *,
    user_id: UUID,
) -> PushPreferences:
    async with session.begin():
        account = await accounts_repositories.get_account(
            session,
            user_id,
            platform,
        )

    if account is None:
        raise PlatformNotLinkedError(f"{platform.title()} is not linked")

    return PushPreferences(
        platform=account.platform,
        push_likes=account.push_likes,
        push_playlists=account.push_playlists,
    )


async def set_preferences(
    session: AsyncSession,
    platform: Platforms,
    request: PushPreferencesRequest,
    *,
    user_id: UUID,
) -> PushPreferences:
    async with session.begin():
        account = await accounts_repositories.set_push_preferences(
            session,
            user_id,
            platform,
            push_likes=request.push_likes,
            push_playlists=request.push_playlists,
        )

    if account is None:
        raise PlatformNotLinkedError(f"{platform.title()} is not linked")

    return PushPreferences(
        platform=account.platform,
        push_likes=account.push_likes,
        push_playlists=account.push_playlists,
    )
