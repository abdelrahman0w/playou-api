from collections.abc import Collection
from uuid import UUID

from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.structs import tables
from src.structs.models import Track
from src.structs.models.responses import CatalogTrack
from src.structs.models.responses import TrackSource


async def _save(
    session: AsyncSession,
    track: Track,
) -> UUID:
    source = tables.TrackSource
    values = {
        "title": track.title,
        "artists": track.artists,
        "album": track.album,
        "duration_ms": track.duration_ms,
        "explicit": track.explicit,
        "artwork_url": track.artwork_url,
    }

    found = await session.scalar(
        select(source).where(
            source.platform == track.platform,
            source.platform_id == track.platform_id,
        ),
    )
    if found is not None:
        await session.execute(
            update(tables.Track)
            .where(tables.Track.id == found.track_id)
            .values(**values),
        )
        found.url = track.url

        return found.track_id

    track_id = (
        await session.scalar(
            select(tables.Track.id).where(tables.Track.isrc == track.isrc),
        )
        if track.isrc
        else None
    )
    if track_id is None:
        statement = insert(tables.Track).values(isrc=track.isrc, **values)
        if track.isrc:
            statement = statement.on_conflict_do_update(
                index_elements=["isrc"],
                index_where=text("isrc is not null"),
                set_=values,
            )
        track_id = (
            await session.execute(statement.returning(tables.Track.id))
        ).scalar_one()

    await session.execute(
        insert(source)
        .values(
            track_id=track_id,
            platform=track.platform,
            platform_id=track.platform_id,
            url=track.url,
        )
        .on_conflict_do_nothing(index_elements=["platform", "platform_id"]),
    )

    return (
        await session.execute(
            select(source.track_id).where(
                source.platform == track.platform,
                source.platform_id == track.platform_id,
            ),
        )
    ).scalar_one()


async def save_platform_tracks(
    session: AsyncSession,
    tracks: list[Track],
) -> list[CatalogTrack]:
    ids = [await _save(session, track) for track in tracks]
    found = await get_tracks(session, ids)

    return [found[track_id] for track_id in ids]


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
