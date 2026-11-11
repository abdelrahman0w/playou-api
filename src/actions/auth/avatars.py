import asyncio
import secrets
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.actions import rate_limit as rate_limit_actions
from src.exceptions import InvalidImageError
from src.exceptions import MediaUnavailableError
from src.exceptions import TooManyRequestsError
from src.exceptions import UnsupportedError
from src.providers import logger
from src.repositories import auth as auth_repositories
from src.services import MediaService
from src.settings import settings
from src.utils.avatars import avatar_webp


HOUR = 60 * 60


def ensure_media(media: MediaService | None) -> MediaService:
    if media is None:
        raise UnsupportedError("Profile pictures are turned off")

    return media


async def forget_avatar(media: MediaService | None, key: str | None) -> None:
    if media is None or key is None:
        return

    try:
        await media.delete(key)
    except MediaUnavailableError as error:
        logger.warning(
            "[Avatars] Old Picture Not Deleted",
            key=key,
            error=error.message,
        )


async def store_avatar(
    redis: Redis,
    media: MediaService | None,
    user_id: UUID,
    data: bytes,
) -> str:
    media = ensure_media(media)
    result = await rate_limit_actions.hit(
        redis,
        f"avatars:{user_id}",
        limit=settings.avatars.per_user_hour,
        window_seconds=HOUR,
    )
    if not result.allowed:
        raise TooManyRequestsError(
            "You have changed your picture a lot, try again later",
            retry_after_seconds=result.reset,
        )

    picture = await asyncio.to_thread(
        avatar_webp,
        data,
        size=settings.avatars.pixels,
    )
    if picture is None:
        raise InvalidImageError("That file is not a picture we can use")

    key = f"avatars/{user_id}/{secrets.token_urlsafe(12)}.webp"
    await media.put(key, picture, content_type="image/webp")

    return key


async def set_avatar(
    session: AsyncSession,
    user_id: UUID,
    key: str | None,
) -> str | None:
    return await auth_repositories.swap_avatar(session, user_id, key)
