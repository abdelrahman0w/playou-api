from datetime import datetime
from uuid import UUID

from sqlalchemy import and_
from sqlalchemy import exists
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from src.structs import tables
from src.structs.enums import LyricsStatuses


async def get_lyrics(
    session: AsyncSession,
    track_id: UUID,
) -> tables.TrackLyrics | None:
    return await session.get(tables.TrackLyrics, track_id)


async def save_lyrics(
    session: AsyncSession,
    track_id: UUID,
    *,
    status: LyricsStatuses,
    synced: str | None,
    plain: str | None,
    source_id: int | None,
    now: datetime,
) -> None:
    lyrics = tables.TrackLyrics
    values = {
        "status": status,
        "synced": synced,
        "plain": plain,
        "source": "LRCLIB" if source_id is not None else None,
        "source_id": source_id,
        "checked_at": now,
    }
    await session.execute(
        insert(lyrics)
        .values(track_id=track_id, **values)
        .on_conflict_do_update(
            index_elements=["track_id"],
            set_={**values, "updated_at": func.now()},
        ),
    )


async def hide_lyrics(session: AsyncSession, track_id: UUID, *, now: datetime) -> bool:
    lyrics = tables.TrackLyrics
    hidden = await session.scalar(
        update(lyrics)
        .where(lyrics.track_id == track_id, lyrics.status == LyricsStatuses.FOUND)
        .values(status=LyricsStatuses.HIDDEN, checked_at=now)
        .returning(lyrics.track_id),
    )

    return hidden is not None


async def move_lyrics(session: AsyncSession, keep: UUID, drop: UUID) -> None:
    lyrics = tables.TrackLyrics
    kept = aliased(lyrics)
    await session.execute(
        update(lyrics)
        .where(
            lyrics.track_id == drop,
            ~exists(select(kept.track_id).where(kept.track_id == keep)),
        )
        .values(track_id=keep),
    )


async def record_report(
    session: AsyncSession,
    user_id: UUID,
    track_id: UUID,
    source_id: int,
) -> None:
    await session.execute(
        insert(tables.LyricsReport)
        .values(user_id=user_id, track_id=track_id, source_id=source_id)
        .on_conflict_do_nothing(index_elements=["user_id", "track_id", "source_id"]),
    )


async def has_reported(
    session: AsyncSession,
    user_id: UUID,
    track_id: UUID,
    source_id: int,
) -> bool:
    report = tables.LyricsReport

    return bool(
        await session.scalar(
            select(
                exists().where(
                    report.user_id == user_id,
                    report.track_id == track_id,
                    report.source_id == source_id,
                ),
            ),
        ),
    )


async def count_reports(session: AsyncSession, track_id: UUID, source_id: int) -> int:
    report = tables.LyricsReport

    return (
        await session.scalar(
            select(func.count()).where(
                report.track_id == track_id,
                report.source_id == source_id,
            ),
        )
        or 0
    )


async def most_reported(
    session: AsyncSession,
    *,
    limit: int,
) -> list[dict[str, object]]:
    report = tables.LyricsReport
    track = tables.Track
    lyrics = tables.TrackLyrics
    rows = await session.execute(
        select(
            report.track_id,
            track.title,
            track.artists,
            report.source_id,
            lyrics.status,
            func.count().label("reports"),
            func.max(report.created_at).label("latest"),
        )
        .join(track, track.id == report.track_id)
        .join(
            lyrics,
            and_(
                lyrics.track_id == report.track_id,
                lyrics.source_id == report.source_id,
            ),
        )
        .group_by(
            report.track_id,
            track.title,
            track.artists,
            report.source_id,
            lyrics.status,
        )
        .order_by(func.count().desc(), func.max(report.created_at).desc())
        .limit(limit),
    )

    return [
        {
            "track_id": str(row.track_id),
            "title": row.title,
            "artists": list(row.artists),
            "lrclib_id": row.source_id,
            "status": row.status,
            "reports": row.reports,
            "latest": row.latest.isoformat(),
        }
        for row in rows
    ]


async def move_reports(session: AsyncSession, keep: UUID, drop: UUID) -> None:
    report = tables.LyricsReport
    kept = aliased(report)
    await session.execute(
        update(report)
        .where(
            report.track_id == drop,
            ~exists(
                select(kept.id).where(
                    kept.track_id == keep,
                    kept.user_id == report.user_id,
                    kept.source_id == report.source_id,
                ),
            ),
        )
        .values(track_id=keep),
    )
