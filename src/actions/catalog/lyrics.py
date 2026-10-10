from datetime import datetime
from datetime import timedelta
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.actions import rate_limit as rate_limit_actions
from src.exceptions import NotFoundError
from src.exceptions import PlatformUnavailableError
from src.exceptions import TooManyRequestsError
from src.exceptions import UnsupportedError
from src.providers import logger
from src.repositories import catalog as catalog_repositories
from src.services import LrclibService
from src.services.lrclib import LrclibRecord
from src.settings import settings
from src.structs import tables
from src.structs.enums import LyricsStatuses
from src.structs.models.responses import CatalogTrack
from src.structs.models.responses import Lyrics
from src.utils.lyrics import timed_lines
from src.utils.single_flight import single_flight


HOUR = 60 * 60
SAME_LENGTH_SECONDS = 3


def _ensure_enabled(lrclib: LrclibService | None) -> LrclibService:
    if lrclib is None:
        raise UnsupportedError("Lyrics are turned off")

    return lrclib


def _fresh(saved: tables.TrackLyrics, now: datetime) -> bool:
    lyrics = settings.lyrics
    days = {
        LyricsStatuses.FOUND: lyrics.found_days,
        LyricsStatuses.INSTRUMENTAL: lyrics.found_days,
        LyricsStatuses.MISSING: lyrics.missing_days,
        LyricsStatuses.HIDDEN: lyrics.hidden_days,
    }.get(saved.status, 0)

    return saved.checked_at + timedelta(days=days) > now


def _answer(saved: tables.TrackLyrics) -> Lyrics:
    if saved.status != LyricsStatuses.FOUND:
        return Lyrics(status=saved.status)

    return Lyrics(
        status=saved.status,
        lines=timed_lines(saved.synced) if saved.synced else [],
        plain=saved.plain,
        source=saved.source,
    )


def _status(record: LrclibRecord) -> LyricsStatuses:
    if record.synced or record.plain:
        return LyricsStatuses.FOUND
    if record.instrumental:
        return LyricsStatuses.INSTRUMENTAL

    return LyricsStatuses.MISSING


def _best(records: list[LrclibRecord], duration_ms: int | None) -> LrclibRecord | None:
    fitting = [
        record
        for record in records
        if _status(record) != LyricsStatuses.MISSING
        and (
            duration_ms is None
            or (
                record.duration is not None
                and abs(record.duration - duration_ms / 1000) <= SAME_LENGTH_SECONDS
            )
        )
    ]

    return min(
        fitting,
        key=lambda record: (
            not record.synced,
            not record.plain,
            abs((record.duration or 0) - (duration_ms or 0) / 1000),
        ),
        default=None,
    )


async def _look_up(lrclib: LrclibService, track: CatalogTrack) -> LrclibRecord | None:
    artist = track.artists[0] if track.artists else ""
    if track.album and track.duration_ms:
        found = await lrclib.get(
            title=track.title,
            artist=artist,
            album=track.album,
            duration_seconds=round(track.duration_ms / 1000),
        )
        if found is not None and _status(found) != LyricsStatuses.MISSING:
            return found

    return _best(
        await lrclib.search(title=track.title, artist=artist),
        track.duration_ms,
    )


async def _fetch(
    session_factory: async_sessionmaker[AsyncSession],
    lrclib: LrclibService,
    track: CatalogTrack,
    *,
    now: datetime,
) -> Lyrics:
    try:
        record = await _look_up(lrclib, track)
    except PlatformUnavailableError as exc:
        logger.warning(
            "[Lyrics] LRCLIB Unavailable",
            track_id=str(track.id),
            error=str(exc.__cause__ or exc),
        )

        return Lyrics(status=LyricsStatuses.UNAVAILABLE)

    async with session_factory() as session, session.begin():
        await catalog_repositories.save_lyrics(
            session,
            track.id,
            status=_status(record) if record else LyricsStatuses.MISSING,
            synced=record.synced if record else None,
            plain=record.plain if record else None,
            source_id=record.id if record else None,
            now=now,
        )
        saved = await catalog_repositories.get_lyrics(session, track.id)

    return _answer(saved) if saved else Lyrics(status=LyricsStatuses.MISSING)


async def track_lyrics(
    session_factory: async_sessionmaker[AsyncSession],
    lrclib: LrclibService | None,
    track_id: UUID,
    *,
    now: datetime,
) -> Lyrics:
    service = _ensure_enabled(lrclib)
    async with session_factory() as session, session.begin():
        track = (await catalog_repositories.get_tracks(session, [track_id])).get(
            track_id,
        )
        saved = await catalog_repositories.get_lyrics(session, track_id)
    if track is None:
        raise NotFoundError("The track does not exist")
    if saved is not None and _fresh(saved, now):
        return _answer(saved)

    return await single_flight(
        f"lyrics:{track_id}",
        lambda: _fetch(session_factory, service, track, now=now),
    )


async def report_lyrics(
    session: AsyncSession,
    redis: Redis,
    lrclib: LrclibService | None,
    track_id: UUID,
    *,
    user_id: UUID,
    now: datetime,
) -> None:
    _ensure_enabled(lrclib)
    result = await rate_limit_actions.hit(
        redis,
        f"lyrics-reports:{user_id}",
        limit=settings.lyrics.reports_per_user_hour,
        window_seconds=HOUR,
    )
    if not result.allowed:
        raise TooManyRequestsError(
            "You have reported a lot of lyrics, try again later",
            retry_after_seconds=result.reset,
        )
    if not await catalog_repositories.hide_lyrics(session, track_id, now=now):
        raise NotFoundError("This song has no lyrics to report")
