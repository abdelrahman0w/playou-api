from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID
from uuid import uuid7

from sqlalchemy import ARRAY
from sqlalchemy import Integer
from sqlalchemy import Row
from sqlalchemy import Text
from sqlalchemy import Uuid
from sqlalchemy import bindparam
from sqlalchemy import exists
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy import tuple_
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.settings import settings
from src.structs import tables
from src.structs.enums import Platforms
from src.structs.models import Track
from src.structs.models.responses import CatalogTrack
from src.structs.models.responses import TrackSource
from src.utils.matching import SAME_DURATION_MS
from src.utils.matching import normalize_title
from src.utils.matching import same_song
from src.utils.search import matching
from src.utils.sql import any_of


BATCH = 500
VALUES = ("title", "artists", "album", "duration_ms", "explicit", "artwork_url")


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


NEAREST = (
    text(
        "select wanted.n, found.id, found.title, found.artists, found.duration_ms, "
        "found.isrc "
        "from unnest(:durations, :titles) "
        "with ordinality as wanted(duration_ms, title, n) "
        "cross join lateral ("
        "select id, title, artists, duration_ms, isrc from tracks "
        "where duration_ms between wanted.duration_ms - :window "
        "and wanted.duration_ms + :window "
        "order by sort_title <-> search_fold(wanted.title) "
        "limit :limit"
        ") as found",
    )
    .bindparams(
        bindparam("durations", type_=ARRAY(Integer)),
        bindparam("titles", type_=ARRAY(Text)),
    )
    .columns(
        n=Integer,
        id=Uuid,
        title=Text,
        artists=ARRAY(Text),
        duration_ms=Integer,
        isrc=Text,
    )
)
NEAREST_TITLES = 50

type Candidate = Row[tuple[UUID, str, list[str], int | None, str | None]]


def _pick(
    timed: list[Track],
    candidates: list[list[Candidate]],
) -> dict[tuple[Platforms, str], UUID]:
    matched: dict[tuple[Platforms, str], UUID] = {}
    claimed: set[UUID] = set()
    for track, found in zip(timed, candidates, strict=True):
        for candidate in sorted(found, key=lambda candidate: candidate.isrc is None):
            if track.isrc and (candidate.isrc is not None or candidate.id in claimed):
                continue
            if same_song(
                (track.title, track.artists, track.duration_ms),
                (candidate.title, list(candidate.artists), candidate.duration_ms),
                across_scripts=settings.catalog.match_across_scripts,
            ):
                matched[(track.platform, track.platform_id)] = candidate.id
                if track.isrc:
                    claimed.add(candidate.id)
                break

    return matched


async def _nearest_matches(
    session: AsyncSession,
    timed: list[Track],
) -> dict[tuple[Platforms, str], UUID]:
    rows = await session.execute(
        NEAREST,
        {
            "durations": [track.duration_ms for track in timed],
            "titles": [normalize_title(track.title) for track in timed],
            "window": SAME_DURATION_MS,
            "limit": NEAREST_TITLES,
        },
    )
    candidates: list[list[Candidate]] = [[] for _ in timed]
    for row in rows:
        candidates[row.n - 1].append(row)

    return _pick(timed, candidates)


async def _matches(
    session: AsyncSession,
    tracks: list[Track],
) -> dict[tuple[Platforms, str], UUID]:
    timed = [track for track in tracks if track.duration_ms is not None]
    if not timed:
        return {}
    if not settings.catalog.match_across_scripts:
        return await _nearest_matches(session, timed)

    return await _window_matches(session, timed)


async def _window_matches(
    session: AsyncSession,
    timed: list[Track],
) -> dict[tuple[Platforms, str], UUID]:
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
    found = list(candidates.all())

    return _pick(timed, [found] * len(timed))  # type: ignore[list-item]


@dataclass(frozen=True)
class _Stored:
    source_id: UUID
    track_id: UUID
    url: str | None
    isrc: str | None
    values: dict[str, object]


async def _stored(
    session: AsyncSession,
    keys: list[tuple[Platforms, str]],
) -> dict[tuple[Platforms, str], _Stored]:
    source = tables.TrackSource
    track = tables.Track
    rows = await session.execute(
        select(
            source.platform,
            source.platform_id,
            source.id.label("source_id"),
            source.url,
            track.id.label("track_id"),
            track.isrc,
            *(getattr(track, column) for column in VALUES),
        )
        .join(track, track.id == source.track_id)
        .where(tuple_(source.platform, source.platform_id).in_(keys)),
    )

    return {
        (row.platform, row.platform_id): _Stored(
            source_id=row.source_id,
            track_id=row.track_id,
            url=row.url,
            isrc=row.isrc,
            values={column: getattr(row, column) for column in VALUES},
        )
        for row in rows
    }


async def _save_batch(
    session: AsyncSession,
    tracks: list[Track],
) -> dict[tuple[Platforms, str], UUID]:
    by_key = {(track.platform, track.platform_id): track for track in tracks}
    keys = list(by_key)
    known = await _stored(session, keys)

    changed_tracks = [
        {"id": row.track_id, **values}
        for key in keys
        if (row := known.get(key)) is not None
        and (by_key[key].isrc is not None or row.isrc is None)
        and (values := _values(by_key[key])) != row.values
    ]
    if changed_tracks:
        await session.execute(update(tables.Track), changed_tracks)
    changed_sources = [
        {"id": row.source_id, "url": by_key[key].url}
        for key in keys
        if (row := known.get(key)) is not None and by_key[key].url != row.url
    ]
    if changed_sources:
        await session.execute(update(tables.TrackSource), changed_sources)

    new = [by_key[key] for key in keys if key not in known]
    if not new:
        return {key: stored.track_id for key, stored in known.items()}

    isrcs = {track.isrc for track in new if track.isrc}
    by_isrc: dict[str, UUID] = {}
    if isrcs:
        rows = await session.execute(
            select(tables.Track.isrc, tables.Track.id).where(
                tables.Track.isrc.in_(isrcs),
            ),
        )
        by_isrc = {isrc: track_id for isrc, track_id in rows if isrc is not None}

    matched = await _matches(
        session,
        [track for track in new if not track.isrc or track.isrc not in by_isrc],
    )

    rows_to_insert: list[dict[str, object]] = []
    rows_to_claim: list[dict[str, object]] = []
    track_ids: dict[tuple[Platforms, str], UUID] = {}
    for track in new:
        if track.isrc and track.isrc in by_isrc:
            track_id = by_isrc[track.isrc]
        elif (track.platform, track.platform_id) in matched:
            track_id = matched[(track.platform, track.platform_id)]
            if track.isrc:
                by_isrc[track.isrc] = track_id
                rows_to_claim.append(
                    {"id": track_id, "isrc": track.isrc, **_values(track)}
                )
        else:
            track_id = uuid7()
            rows_to_insert.append(
                {"id": track_id, "isrc": track.isrc, **_values(track)}
            )
            if track.isrc:
                by_isrc[track.isrc] = track_id
        track_ids[(track.platform, track.platform_id)] = track_id

    if rows_to_claim:
        await session.execute(update(tables.Track), rows_to_claim)
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


def _lock_order(track: Track) -> tuple[bool, str, str, str]:
    return track.isrc is None, track.isrc or "", track.platform, track.platform_id


async def save_platform_track_ids(
    session: AsyncSession,
    tracks: list[Track],
) -> list[UUID]:
    ordered = sorted(tracks, key=_lock_order)
    ids: dict[tuple[Platforms, str], UUID] = {}
    for start in range(0, len(ordered), BATCH):
        ids |= await _save_batch(session, ordered[start : start + BATCH])

    return [ids[(track.platform, track.platform_id)] for track in tracks]


async def save_platform_tracks(
    session: AsyncSession,
    tracks: list[Track],
) -> list[CatalogTrack]:
    ordered = await save_platform_track_ids(session, tracks)
    found = await get_tracks(session, ordered)

    return [found[track_id] for track_id in ordered]


async def get_tracks(
    session: AsyncSession,
    track_ids: Collection[UUID],
) -> dict[UUID, CatalogTrack]:
    if not track_ids:
        return {}

    tracks = await session.scalars(
        select(tables.Track).where(any_of(tables.Track.id, track_ids)),
    )
    sources = await session.scalars(
        select(tables.TrackSource)
        .where(any_of(tables.TrackSource.track_id, track_ids))
        .order_by(tables.TrackSource.created_at, tables.TrackSource.id),
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


async def tracks_changed(
    session: AsyncSession,
    track_ids: Collection[UUID],
) -> tuple[int, datetime | None]:
    if not track_ids:
        return 0, None

    track = tables.Track
    source = tables.TrackSource
    row = (
        await session.execute(
            select(
                func.count(func.distinct(track.id)),
                func.greatest(func.max(track.updated_at), func.max(source.updated_at)),
            )
            .select_from(track)
            .outerjoin(source, source.track_id == track.id)
            .where(any_of(track.id, track_ids)),
        )
    ).one()

    return row[0], row[1]


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
        .where(any_of(source.track_id, track_ids), source.platform == platform)
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


async def search_catalog(
    session: AsyncSession,
    platform: Platforms,
    query: str,
    *,
    limit: int,
) -> list[CatalogTrack]:
    track = tables.Track
    source = tables.TrackSource
    searched = func.track_search_text(track.title, track.artists, track.album)
    ids = list(
        await session.scalars(
            select(track.id)
            .where(
                exists().where(
                    source.track_id == track.id,
                    source.platform == platform,
                    source.embed_blocked_at.is_(None),
                ),
                *matching(searched, query),
            )
            .order_by(
                func.similarity(searched, func.search_fold(query)).desc(), track.id
            )
            .limit(limit),
        ),
    )
    found = await get_tracks(session, ids)

    return [found[id_] for id_ in ids if id_ in found]
