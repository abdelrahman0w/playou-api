from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from src.exceptions import ForbiddenError
from src.exceptions import UnsupportedError
from src.providers import logger
from src.repositories import accounts as accounts_repositories
from src.repositories import auth as auth_repositories
from src.repositories import library as library_repositories
from src.settings import settings
from src.structs.enums import CacheKeys
from src.structs.enums import Platforms
from src.structs.models.responses import PlatformData


def ensure_allowed() -> None:
    if not settings.data.deletion_enabled:
        raise ForbiddenError("Deleting data is turned off")


async def _linked(
    session: AsyncSession,
    user_id: UUID,
) -> set[Platforms]:
    accounts = await accounts_repositories.list_accounts(session, user_id)

    return {account.platform for account in accounts}


async def leftovers(
    session: AsyncSession,
    user_id: UUID,
) -> list[PlatformData]:
    found = await library_repositories.leftovers(
        session,
        user_id,
        await _linked(session, user_id),
    )

    return [
        PlatformData(platform=platform, likes=likes, playlists=playlists)
        for platform, (likes, playlists) in sorted(found.items())
    ]


async def remove_platform_data(
    session: AsyncSession,
    user_id: UUID,
    platform: Platforms,
) -> None:
    linked = await _linked(session, user_id)
    if platform in linked:
        raise UnsupportedError(f"Unlink {platform.title()} before removing its data")

    likes, playlists = await library_repositories.delete_platform_data(
        session,
        user_id,
        platform,
        linked,
    )
    logger.info(
        "[Data] Platform Data Removed",
        platform=platform,
        likes=likes,
        playlists=playlists,
    )


async def clear_library(
    session: AsyncSession,
    user_id: UUID,
    *,
    unlink: bool,
) -> None:
    await library_repositories.delete_library(session, user_id)

    if unlink:
        await accounts_repositories.delete_accounts(session, user_id)

    logger.info(
        "[Data] Library Cleared",
        unlinked=unlink,
    )


async def delete_user(session: AsyncSession, redis: Redis, user_id: UUID) -> None:
    hashes = await auth_repositories.delete_user(session, user_id)
    try:
        if hashes:
            await redis.delete(
                *(CacheKeys.AUTH_SESSION.format(token=hashed) for hashed in hashes),
            )
    except RedisError:
        pass

    logger.info("[Data] Account Deleted")
