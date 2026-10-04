from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.exceptions import NotFoundError
from src.exceptions import PlaybackSessionChangedError
from src.repositories import catalog as catalog_repositories
from src.repositories import playback as playback_repositories
from src.structs.models import StoredPlaybackSession
from src.structs.models.requests import DeviceRequest
from src.structs.models.requests import SavePlaybackSessionRequest
from src.structs.models.responses import PlaybackSession
from src.structs.models.responses import PlaybackSessionSaved


async def _with_tracks(
    session: AsyncSession,
    stored: StoredPlaybackSession,
) -> PlaybackSession:
    current = stored.current_track_id
    ids = {
        *stored.track_ids,
        *stored.up_next,
        *([current] if current else []),
    }
    tracks = await catalog_repositories.get_tracks(session, ids)

    return PlaybackSession(
        device_id=stored.device_id,
        device_name=stored.device_name,
        platform=stored.platform,
        source=stored.source,
        tracks=[tracks[id_] for id_ in stored.track_ids if id_ in tracks],
        cursor=stored.cursor,
        current=tracks.get(current) if current else None,
        up_next=[tracks[id_] for id_ in stored.up_next if id_ in tracks],
        playing=stored.playing,
        position_ms=stored.position_ms,
        position_at=stored.position_at,
        version=stored.version,
    )


async def get_session(
    session: AsyncSession,
    user_id: UUID,
) -> PlaybackSession | None:
    stored = await playback_repositories.get_session(session, user_id)

    return await _with_tracks(session, stored) if stored else None


async def save_session(
    session: AsyncSession,
    user_id: UUID,
    request: SavePlaybackSessionRequest,
    *,
    now: datetime,
) -> PlaybackSessionSaved:
    stored = await playback_repositories.save_session(
        session, user_id, request, now=now
    )
    if stored is None:
        raise PlaybackSessionChangedError("Another device changed what is playing")

    return PlaybackSessionSaved(
        version=stored.version,
        position_at=stored.position_at,
    )


async def claim_session(
    session: AsyncSession,
    user_id: UUID,
    request: DeviceRequest,
    *,
    now: datetime,
) -> PlaybackSession:
    stored = await playback_repositories.get_session(session, user_id)
    if stored is None:
        raise NotFoundError("Nothing is playing")

    position_ms = stored.position_ms
    if stored.playing:
        position_ms += int((now - stored.position_at).total_seconds() * 1000)

    claimed = await playback_repositories.claim_session(
        session,
        user_id,
        device_id=request.device_id,
        device_name=request.device_name,
        position_ms=max(0, position_ms),
        now=now,
    )
    if claimed is None:
        raise NotFoundError("Nothing is playing")

    return await _with_tracks(session, claimed)


async def forget_session(session: AsyncSession, user_id: UUID) -> None:
    await playback_repositories.delete_session(
        session,
        user_id,
    )
