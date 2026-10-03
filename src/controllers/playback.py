from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.actions import playback as playback_actions
from src.services import OAuthPlatform
from src.structs.enums import Platforms
from src.structs.models import PlaybackDevice
from src.structs.models.requests import PlayRequest
from src.structs.models.responses import PlaybackToken


async def playback_token(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    platforms: dict[Platforms, OAuthPlatform],
    platform: Platforms,
    *,
    user_id: UUID,
    now: datetime,
    rejected: str | None = None,
) -> PlaybackToken:
    async with session.begin():
        return await playback_actions.playback_token(
            session,
            session_factory,
            platforms,
            user_id=user_id,
            platform=platform,
            now=now,
            rejected=rejected,
        )


async def list_devices(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    platforms: dict[Platforms, OAuthPlatform],
    platform: Platforms,
    *,
    user_id: UUID,
    now: datetime,
) -> list[PlaybackDevice]:
    async with session.begin():
        return await playback_actions.list_devices(
            session,
            session_factory,
            platforms,
            user_id=user_id,
            platform=platform,
            now=now,
        )


async def play(
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    platforms: dict[Platforms, OAuthPlatform],
    platform: Platforms,
    request: PlayRequest,
    *,
    user_id: UUID,
    now: datetime,
) -> None:
    async with session.begin():
        await playback_actions.play(
            session,
            session_factory,
            platforms,
            request,
            user_id=user_id,
            platform=platform,
            now=now,
        )
