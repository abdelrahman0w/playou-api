import hashlib
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.exceptions import NotFoundError
from src.exceptions import PlaybackSessionChangedError
from src.repositories import catalog as catalog_repositories
from src.repositories import playback as playback_repositories
from src.structs.models import StoredPlaybackSession
from src.structs.models.requests import DeviceRequest
from src.structs.models.requests import PlaybackPositionRequest
from src.structs.models.requests import SavePlaybackSessionRequest
from src.structs.models.responses import PlaybackSession
from src.structs.models.responses import PlaybackSessionSaved


async def _with_tracks(
    session: AsyncSession,
    stored: StoredPlaybackSession,
) -> PlaybackSession:
    current = stored.current_track_id
    tracks = await catalog_repositories.get_tracks(session, _queued(stored))

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


@dataclass(frozen=True)
class SessionRead:
    tag: str
    session: PlaybackSession | None = None
    unchanged: bool = False


def _queued(stored: StoredPlaybackSession) -> set[UUID]:
    current = stored.current_track_id

    return {*stored.track_ids, *stored.up_next, *([current] if current else [])}


async def _tag(
    session: AsyncSession,
    user_id: UUID,
    stored: StoredPlaybackSession | None,
) -> str:
    parts: list[object] = [user_id]
    if stored is not None:
        found, changed = await catalog_repositories.tracks_changed(
            session,
            _queued(stored),
        )
        parts += [stored.version, stored.updated_at, found, changed]
    digest = hashlib.blake2b(":".join(map(str, parts)).encode(), digest_size=8)

    return f'"{digest.hexdigest()}"'


def _seen(header: str | None) -> set[str]:
    return {tag.strip().removeprefix("W/") for tag in (header or "").split(",")}


async def get_session(
    session: AsyncSession,
    user_id: UUID,
    *,
    seen: str | None = None,
) -> SessionRead:
    stored = await playback_repositories.get_session(session, user_id)
    tag = await _tag(session, user_id, stored)
    if tag in _seen(seen):
        return SessionRead(tag=tag, unchanged=True)

    return SessionRead(
        tag=tag,
        session=await _with_tracks(session, stored) if stored else None,
    )


async def save_session(
    session: AsyncSession,
    user_id: UUID,
    request: SavePlaybackSessionRequest,
    *,
    now: datetime,
) -> PlaybackSessionSaved:
    saved = await playback_repositories.save_session(session, user_id, request, now=now)
    if saved is None:
        raise PlaybackSessionChangedError("Another device changed what is playing")

    return saved


async def save_position(
    session: AsyncSession,
    user_id: UUID,
    request: PlaybackPositionRequest,
    *,
    now: datetime,
) -> PlaybackSessionSaved:
    saved = await playback_repositories.save_position(
        session, user_id, request, now=now
    )
    if saved is None:
        raise PlaybackSessionChangedError("Another device changed what is playing")

    return saved


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
