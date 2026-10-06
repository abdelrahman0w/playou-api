from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.actions import accounts as accounts_actions
from src.exceptions import NotFoundError
from src.exceptions import PlatformNotLinkedError
from src.exceptions import PlatformScopesMissingError
from src.exceptions import UnsupportedError
from src.repositories import accounts as accounts_repositories
from src.repositories import catalog as catalog_repositories
from src.repositories import library as library_repositories
from src.services import OAuthPlatform
from src.structs.enums import Platforms
from src.structs.models import PlaybackDevice
from src.structs.models import PlaybackRequest
from src.structs.models import StoredAccount
from src.structs.models.requests import PlayRequest
from src.structs.models.responses import PlaybackToken


@dataclass(frozen=True)
class Playable:
    service: OAuthPlatform
    account: StoredAccount


async def playable(
    session: AsyncSession,
    platforms: dict[Platforms, OAuthPlatform],
    *,
    user_id: UUID,
    platform: Platforms,
) -> Playable:
    service = platforms.get(platform)
    if service is None or not service.capabilities.playback:
        raise UnsupportedError(f"{platform.title()} cannot play here")

    account = await accounts_repositories.get_account(session, user_id, platform)
    if account is None:
        raise PlatformNotLinkedError(f"{platform.title()} is not linked")

    if any(scope not in account.scopes for scope in service.playback_scopes):
        raise PlatformScopesMissingError(
            f"Link {platform.title()} again to allow playing on it",
        )

    return Playable(service=service, account=account)


async def playback_token(
    session_factory: async_sessionmaker[AsyncSession],
    target: Playable,
    *,
    now: datetime,
    rejected: str | None = None,
) -> PlaybackToken:
    token, expires_at = await accounts_actions.access_token_until(
        session_factory,
        target.service,
        target.account,
        now=now,
        rejected=rejected,
    )

    return PlaybackToken(access_token=token, expires_at=expires_at)


async def list_devices(
    session_factory: async_sessionmaker[AsyncSession],
    target: Playable,
    *,
    now: datetime,
) -> list[PlaybackDevice]:
    return await accounts_actions.with_token(
        session_factory,
        target.service,
        target.account,
        target.service.devices,
        now=now,
    )


async def _from_tracks(
    session: AsyncSession,
    platform: Platforms,
    request: PlayRequest,
) -> PlaybackRequest:
    track_ids = request.track_ids or []
    found = await catalog_repositories.platform_track_ids(session, track_ids, platform)
    playable = [found[track_id] for track_id in track_ids if track_id in found]
    if not playable:
        raise UnsupportedError(f"{platform.title()} has none of these tracks")

    first = track_ids[request.offset] if request.offset < len(track_ids) else None

    return PlaybackRequest(
        device_id=request.device_id,
        track_ids=playable,
        offset_track_id=found.get(first) if first is not None else None,
        position_ms=request.position_ms,
    )


async def _from_playlist(
    session: AsyncSession,
    platform: Platforms,
    request: PlayRequest,
    *,
    user_id: UUID,
) -> PlaybackRequest:
    if request.playlist_id is None:
        raise NotFoundError("The playlist does not exist")

    playlist = await library_repositories.get_playlist_row(
        session,
        user_id,
        request.playlist_id,
    )
    state = await library_repositories.playlist_sync_state(
        session,
        request.playlist_id,
        platform,
    )
    if playlist is None or playlist.removed_at is not None or state is None:
        raise NotFoundError("The playlist does not exist")

    first = (
        state.platform_ids[request.offset]
        if request.offset < len(state.platform_ids)
        else None
    )
    if state.link is not None:
        return PlaybackRequest(
            device_id=request.device_id,
            playlist_id=state.link.platform_id,
            offset_track_id=first,
            position_ms=request.position_ms,
        )

    if not state.platform_ids:
        raise UnsupportedError(f"{platform.title()} has none of its tracks")

    return PlaybackRequest(
        device_id=request.device_id,
        track_ids=state.platform_ids[:100],
        offset_track_id=first,
        position_ms=request.position_ms,
    )


async def playback_request(
    session: AsyncSession,
    target: Playable,
    request: PlayRequest,
    *,
    user_id: UUID,
) -> PlaybackRequest:
    platform = target.account.platform
    if request.track_ids is not None:
        return await _from_tracks(session, platform, request)

    return await _from_playlist(session, platform, request, user_id=user_id)


async def play(
    session_factory: async_sessionmaker[AsyncSession],
    target: Playable,
    playback: PlaybackRequest,
    *,
    now: datetime,
) -> None:
    await accounts_actions.with_token(
        session_factory,
        target.service,
        target.account,
        lambda token: target.service.play(token, playback),
        now=now,
    )


async def block_embedding(
    session: AsyncSession,
    *,
    platform: Platforms,
    platform_id: str,
    now: datetime,
) -> None:
    if platform != Platforms.YOUTUBE:
        raise UnsupportedError(f"{platform.title()} is not embedded")

    await catalog_repositories.block_embedding(session, platform, platform_id, now)
