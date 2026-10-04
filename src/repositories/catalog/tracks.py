from collections.abc import Collection
from datetime import datetime
from uuid import UUID
from uuid import uuid7

from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy import tuple_
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.structs import tables
from src.structs.enums import Platforms
from src.structs.models import Track
from src.structs.models.responses import CatalogTrack
from src.structs.models.responses import TrackSource
from src.utils.matching import SAME_DURATION_MS
from src.utils.matching import same_song


BATCH = 500


def _values(track: Track) -> dict[str, object]:
    return {
        "title": track.title,
        "artists": track.artists,
        "album": track.album,
        "duration_ms": track.duration_ms,
        "explicit": track.explicit,
        "artwork_url": track.artwork_url,
    }


async def _source_ids(
    session: AsyncSession,
    keys: list[tuple[Platforms, str]],
) -> dict[tuple[Platforms, str], tuple[UUID, UUID]]:
    source = tables.TrackSource
    rows = await session.execute(
        select(source.platform, source.platform_id, source.id, source.track_id).where(
            tuple_(source.platform, source.platform_id).in_(keys),
        ),
    )

    return {
        (platform, platform_id): (source_id, track_id)
        for platform, platform_id, source_id, track_id in rows
    }


async def _matches(
    session: AsyncSession,
    tracks: list[Track],
) -> dict[tuple[Platforms, str], UUID]:
    timed = [track for track in tracks if track.duration_ms is not None]
    if not timed:
        return {}

    row = tables.Track
    candidates = await session.execute(
        select(row.id, row.title, row.artists, row.duration_ms, row.isrc).where(
            or_(
                *(
                    row.duration_ms.between(
                        track.duration_ms - SAME_DURATION_MS,
                        track.duration_ms + SAME_DURATION_MS,
                    )
                    for track in timed
                    if track.duration_ms is not None
                ),
            ),
        ),
    )
    found = sorted(candidates.all(), key=lambda candidate: candidate.isrc is None)

    matched: dict[tuple[Platforms, str], UUID] = {}
    for track in timed:
        for candidate in found:
            if same_song(
                (track.title, track.artists, track.duration_ms),
                (candidate.title, list(candidate.artists), candidate.duration_ms),
            ):
                matched[(track.platform, track.platform_id)] = candidate.id
                break

    return matched


async def _updatable(
    session: AsyncSession,
    known: dict[tuple[Platforms, str], tuple[UUID, UUID]],
    by_key: dict[tuple[Platforms, str], Track],
) -> dict[tuple[Platforms, str], tuple[UUID, UUID]]:
    fuzzy = {key for key in known if by_key[key].isrc is None}
    if not fuzzy:
        return known

    rows = await session.execute(
        select(tables.Track.id).where(
            tables.Track.id.in_({known[key][1] for key in fuzzy}),
            tables.Track.isrc.is_(None),
        ),
    )
    plain = set(rows.scalars())

    return {
        key: ids for key, ids in known.items() if key not in fuzzy or ids[1] in plain
    }


async def _save_batch(
    session: AsyncSession,
    tracks: list[Track],
) -> dict[tuple[Platforms, str], UUID]:
    by_key = {(track.platform, track.platform_id): track for track in tracks}
    keys = list(by_key)
    known = await _source_ids(session, keys)

    if known:
        updatable = await _updatable(session, known, by_key)
        if updatable:
            await session.execute(
                update(tables.Track),
                [
                    {"id": track_id, **_values(by_key[key])}
                    for key, (_, track_id) in updatable.items()
                ],
            )
        await session.execute(
            update(tables.TrackSource),
            [
                {"id": source_id, "url": by_key[key].url}
                for key, (source_id, _) in known.items()
            ],
        )

    new = [by_key[key] for key in keys if key not in known]
    if not new:
        return {key: track_id for key, (_, track_id) in known.items()}

    isrcs = {track.isrc for track in new if track.isrc}
    by_isrc: dict[str, UUID] = {}
    if isrcs:
        rows = await session.execute(
            select(tables.Track.isrc, tables.Track.id).where(
                tables.Track.isrc.in_(isrcs),
            ),
        )
        by_isrc = {isrc: track_id for isrc, track_id in rows if isrc is not None}

    matched = await _matches(session, [track for track in new if not track.isrc])

    rows_to_insert: list[dict[str, object]] = []
    track_ids: dict[tuple[Platforms, str], UUID] = {}
    for track in new:
        if track.isrc and track.isrc in by_isrc:
            track_id = by_isrc[track.isrc]
        elif (track.platform, track.platform_id) in matched:
            track_id = matched[(track.platform, track.platform_id)]
        else:
            track_id = uuid7()
            rows_to_insert.append(
                {"id": track_id, "isrc": track.isrc, **_values(track)}
            )
            if track.isrc:
                by_isrc[track.isrc] = track_id
        track_ids[(track.platform, track.platform_id)] = track_id

    if rows_to_insert:
        await session.execute(
            insert(tables.Track)
            .values(rows_to_insert)
            .on_conflict_do_nothing(
                index_elements=["isrc"],
                index_where=text("isrc is not null"),
            ),
        )
        inserted_isrcs = {row["isrc"] for row in rows_to_insert if row["isrc"]}
        if inserted_isrcs:
            rows = await session.execute(
                select(tables.Track.isrc, tables.Track.id).where(
                    tables.Track.isrc.in_(inserted_isrcs),
                ),
            )
            stored = {isrc: track_id for isrc, track_id in rows}
            for track in new:
                if track.isrc in stored:
                    track_ids[(track.platform, track.platform_id)] = stored[track.isrc]

    await session.execute(
        insert(tables.TrackSource)
        .values(
            [
                {
                    "track_id": track_ids[(track.platform, track.platform_id)],
                    "platform": track.platform,
                    "platform_id": track.platform_id,
                    "url": track.url,
                }
                for track in new
            ],
        )
        .on_conflict_do_nothing(index_elements=["platform", "platform_id"]),
    )

    saved = await _source_ids(session, keys)

    return {key: track_id for key, (_, track_id) in saved.items()}


async def save_platform_tracks(
    session: AsyncSession,
    tracks: list[Track],
) -> list[CatalogTrack]:
    ids: dict[tuple[Platforms, str], UUID] = {}
    for start in range(0, len(tracks), BATCH):
        ids |= await _save_batch(session, tracks[start : start + BATCH])

    ordered = [ids[(track.platform, track.platform_id)] for track in tracks]
    found = await get_tracks(session, ordered)

    return [found[track_id] for track_id in ordered]


async def get_tracks(
    session: AsyncSession,
    track_ids: Collection[UUID],
) -> dict[UUID, CatalogTrack]:
    if not track_ids:
        return {}

    tracks = await session.scalars(
        select(tables.Track).where(tables.Track.id.in_(track_ids)),
    )
    sources = await session.scalars(
        select(tables.TrackSource)
        .where(tables.TrackSource.track_id.in_(track_ids))
        .order_by(tables.TrackSource.created_at),
    )

    by_track: dict[UUID, list[TrackSource]] = {}
    for source in sources:
        by_track.setdefault(source.track_id, []).append(
            TrackSource(
                platform=source.platform,
                platform_id=source.platform_id,
                url=source.url,
                embed_blocked=source.embed_blocked_at is not None,
            ),
        )

    return {
        track.id: CatalogTrack(
            id=track.id,
            title=track.title,
            artists=list(track.artists),
            album=track.album,
            duration_ms=track.duration_ms,
            isrc=track.isrc,
            explicit=track.explicit,
            artwork_url=track.artwork_url,
            sources=by_track.get(track.id, []),
        )
        for track in tracks
    }


async def track_exists(session: AsyncSession, track_id: UUID) -> bool:
    return (
        await session.scalar(select(tables.Track.id).where(tables.Track.id == track_id))
        is not None
    )


async def platform_track_ids(
    session: AsyncSession,
    track_ids: Collection[UUID],
    platform: Platforms,
) -> dict[UUID, str]:
    source = tables.TrackSource
    rows = await session.execute(
        select(source.track_id, source.platform_id)
        .where(source.track_id.in_(track_ids), source.platform == platform)
        .order_by(source.created_at),
    )

    found: dict[UUID, str] = {}
    for track_id, platform_id in rows:
        found.setdefault(track_id, platform_id)

    return found


async def block_embedding(
    session: AsyncSession,
    platform: Platforms,
    platform_id: str,
    now: datetime,
) -> None:
    source = tables.TrackSource
    await session.execute(
        update(source)
        .where(
            source.platform == platform,
            source.platform_id == platform_id,
            source.embed_blocked_at.is_(None),
        )
        .values(embed_blocked_at=now),
    )
