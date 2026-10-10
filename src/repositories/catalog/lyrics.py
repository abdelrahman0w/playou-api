from datetime import datetime
from uuid import UUID

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
