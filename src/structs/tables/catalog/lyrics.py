from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger
from sqlalchemy import DateTime
from sqlalchemy import Enum
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import UniqueConstraint
from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column

from src.structs.enums import LyricsStatuses
from src.structs.tables.base import Base


def _values(
    enum: type[LyricsStatuses],
) -> list[str]:
    return [member.value for member in enum]


class TrackLyrics(Base):
    __tablename__ = "track_lyrics"

    track_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tracks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    status: Mapped[LyricsStatuses] = mapped_column(
        Enum(LyricsStatuses, native_enum=False, length=32, values_callable=_values),
    )
    synced: Mapped[str | None] = mapped_column(Text)
    plain: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(32))
    source_id: Mapped[int | None] = mapped_column(BigInteger)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LyricsReport(Base):
    __tablename__ = "lyrics_reports"
    __table_args__ = (
        UniqueConstraint("user_id", "track_id", "source_id"),
        Index(None, "track_id", "source_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
    )
    track_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tracks.id", ondelete="CASCADE"),
    )
    source_id: Mapped[int] = mapped_column(BigInteger)
