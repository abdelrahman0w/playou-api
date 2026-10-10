from bisect import bisect_left
from bisect import bisect_right
from typing import Any
from uuid import UUID

from sqlalchemy import CursorResult
from sqlalchemy import Row
from sqlalchemy import Uuid
from sqlalchemy import any_
from sqlalchemy import case
from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import literal
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy import tuple_
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from src.structs import tables
from src.structs.models import DuplicateTrack
from src.utils.matching import SAME_DURATION_MS
from src.utils.matching import same_song


type Candidate = Row[UUID, str, list[str], int | None, str | None]


def _rank(track: Candidate) -> tuple[bool, bool, UUID]:
    return (
        track.isrc is None,
        track.isrc is not None and track.isrc != track.isrc.upper(),
        track.id,
    )


async def find_duplicates(
    session: AsyncSession,
    *,
    across_scripts: bool,
) -> list[DuplicateTrack]:
    row = tables.Track
    tracks = sorted(
        (
            await session.execute(
                select(row.id, row.title, row.artists, row.duration_ms, row.isrc),
            )
        ).all(),
        key=_rank,
    )
    by_id = {track.id: track for track in tracks}
    into: dict[UUID, UUID] = {}

    by_isrc: dict[str, UUID] = {}
    for track in tracks:
        if track.isrc is None:
            continue
        isrc = track.isrc.upper()
        if isrc in by_isrc:
            into[track.id] = by_isrc[isrc]
        else:
            by_isrc[isrc] = track.id

    timed = sorted(
        (track for track in tracks if track.duration_ms is not None),
        key=lambda track: track.duration_ms or 0,
    )
    durations = [track.duration_ms or 0 for track in timed]
    for track in tracks:
        if track.isrc is not None or track.duration_ms is None:
            continue
        window = timed[
            bisect_left(durations, track.duration_ms - SAME_DURATION_MS) : bisect_right(
                durations,
                track.duration_ms + SAME_DURATION_MS,
            )
        ]
        for candidate in sorted(window, key=_rank):
            if _rank(candidate) >= _rank(track):
                break
            if same_song(
                (track.title, list(track.artists), track.duration_ms),
                (candidate.title, list(candidate.artists), candidate.duration_ms),
                across_scripts=across_scripts,
            ):
                into[track.id] = candidate.id
                break

    def root(track_id: UUID) -> UUID:
        while track_id in into:
            track_id = into[track_id]

        return track_id

    return [
        DuplicateTrack(
            keep=root(drop),
            drop=drop,
            title=by_id[root(drop)].title,
            duplicate_title=by_id[drop].title,
        )
        for drop in into
    ]


async def _move_entries(
    session: AsyncSession,
    table: type[tables.Like] | type[tables.PlaylistItem],
    owner: str,
    at: str,
    keep: UUID,
    drop: UUID,
    *,
    newest: bool,
) -> None:
    pair = (keep, drop)
    other = aliased(table)
    mine, theirs = getattr(table, at), getattr(other, at)
    if newest:
        mine, theirs = theirs, mine
    await session.execute(
        delete(table).where(
            table.track_id.in_(pair),
            other.track_id.in_(pair),
            getattr(other, owner) == getattr(table, owner),
            other.id != table.id,
            tuple_(table.removed_at.is_not(None), mine, table.id)
            > tuple_(other.removed_at.is_not(None), theirs, other.id),
        ),
    )
    await session.execute(
        update(table).where(table.track_id == drop).values(track_id=keep),
    )


async def merge_track(
    session: AsyncSession,
    keep: UUID,
    drop: UUID,
) -> None:
    await _move_entries(
        session,
        tables.Like,
        "user_id",
        "liked_at",
        keep,
        drop,
        newest=True,
    )
    await _move_entries(
        session,
        tables.PlaylistItem,
        "playlist_id",
        "added_at",
        keep,
        drop,
        newest=False,
    )

    await session.execute(
        update(tables.TrackSource)
        .where(tables.TrackSource.track_id == drop)
        .values(track_id=keep),
    )

    await session.execute(
        update(tables.Share).where(tables.Share.track_id == drop).values(track_id=keep),
    )

    item = tables.CopyItem
    kept = aliased(item)
    await session.execute(
        delete(item).where(
            item.track_id == drop,
            kept.copy_id == item.copy_id,
            kept.track_id == keep,
        ),
    )
    await session.execute(
        update(item).where(item.track_id == drop).values(track_id=keep),
    )

    playback = tables.PlaybackSession
    await session.execute(
        update(playback)
        .where(
            or_(
                literal(drop, Uuid) == any_(playback.track_ids),
                literal(drop, Uuid) == any_(playback.up_next),
                playback.current_track_id == drop,
            ),
        )
        .values(
            track_ids=func.array_replace(playback.track_ids, drop, keep),
            up_next=func.array_replace(playback.up_next, drop, keep),
            current_track_id=case(
                (playback.current_track_id == drop, keep),
                else_=playback.current_track_id,
            ),
            version=playback.version + 1,
        ),
    )

    await session.execute(delete(tables.Track).where(tables.Track.id == drop))


async def uppercase_isrcs(session: AsyncSession) -> int:
    result: CursorResult[Any] = await session.execute(  # type: ignore[assignment]
        update(tables.Track)
        .where(tables.Track.isrc != func.upper(tables.Track.isrc))
        .values(isrc=func.upper(tables.Track.isrc)),
    )

    return result.rowcount
