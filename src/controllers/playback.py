import asyncio
import contextlib
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.actions import playback as playback_actions
from src.services import OAuthPlatform
from src.structs.enums import Platforms
from src.structs.models import PlaybackDevice
from src.structs.models.requests import DeviceRequest
from src.structs.models.requests import EmbedBlockedRequest
from src.structs.models.requests import PlayRequest
from src.structs.models.requests import SavePlaybackSessionRequest
from src.structs.models.responses import PlaybackSession
from src.structs.models.responses import PlaybackSessionSaved
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
        target = await playback_actions.playable(
            session,
            platforms,
            user_id=user_id,
            platform=platform,
        )

    return await playback_actions.playback_token(
        session_factory,
        target,
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
        target = await playback_actions.playable(
            session,
            platforms,
            user_id=user_id,
            platform=platform,
        )

    return await playback_actions.list_devices(session_factory, target, now=now)


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
        target = await playback_actions.playable(
            session,
            platforms,
            user_id=user_id,
            platform=platform,
        )
        playback = await playback_actions.playback_request(
            session,
            target,
            request,
            user_id=user_id,
        )

    await playback_actions.play(session_factory, target, playback, now=now)


async def block_embedding(
    session: AsyncSession,
    platform: Platforms,
    request: EmbedBlockedRequest,
    *,
    now: datetime,
) -> None:
    async with session.begin():
        await playback_actions.block_embedding(
            session,
            platform=platform,
            platform_id=request.platform_id,
            now=now,
        )


async def get_session(
    session: AsyncSession,
    changes: playback_actions.PlaybackChanges,
    *,
    user_id: UUID,
    seen: str | None = None,
    wait: float = 0,
) -> playback_actions.SessionRead:
    if wait <= 0:
        async with session.begin():
            return await playback_actions.get_session(session, user_id, seen=seen)

    with changes.watch(user_id) as changed:
        async with session.begin():
            read = await playback_actions.get_session(session, user_id, seen=seen)
        if not read.unchanged:
            return read

        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(changed.wait(), timeout=wait)
        if not changed.is_set():
            return read

    async with session.begin():
        return await playback_actions.get_session(session, user_id, seen=seen)


async def save_session(
    session: AsyncSession,
    request: SavePlaybackSessionRequest,
    *,
    user_id: UUID,
    now: datetime,
) -> PlaybackSessionSaved:
    async with session.begin():
        return await playback_actions.save_session(session, user_id, request, now=now)


async def claim_session(
    session: AsyncSession,
    request: DeviceRequest,
    *,
    user_id: UUID,
    now: datetime,
) -> PlaybackSession:
    async with session.begin():
        return await playback_actions.claim_session(session, user_id, request, now=now)


async def forget_session(session: AsyncSession, *, user_id: UUID) -> None:
    async with session.begin():
        await playback_actions.forget_session(session, user_id)
