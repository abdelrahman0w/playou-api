from uuid import UUID

from sqlalchemy import ARRAY
from sqlalchemy import Boolean
from sqlalchemy import Enum
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import UniqueConstraint
from sqlalchemy import Uuid
from sqlalchemy import text
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column

from src.structs.enums import Platforms
from src.structs.tables.base import Base


def _values(enum: type[Platforms]) -> list[str]:
    return [member.value for member in enum]


class Track(Base):
    __tablename__ = "tracks"
    __table_args__ = (
        Index(
            None,
            "isrc",
            unique=True,
            postgresql_where=text("isrc is not null"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("uuidv7()"),
    )
    isrc: Mapped[str | None] = mapped_column(String(12))
    title: Mapped[str] = mapped_column(Text)
    artists: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    album: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    explicit: Mapped[bool | None] = mapped_column(Boolean)
    artwork_url: Mapped[str | None] = mapped_column(Text)


class TrackSource(Base):
    __tablename__ = "track_sources"
    __table_args__ = (
        UniqueConstraint("platform", "platform_id"),
        Index(None, "track_id"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("uuidv7()"),
    )
    track_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tracks.id", ondelete="CASCADE"),
    )
    platform: Mapped[Platforms] = mapped_column(
        Enum(Platforms, native_enum=False, length=32, values_callable=_values),
    )
    platform_id: Mapped[str] = mapped_column(String(255))
    url: Mapped[str | None] = mapped_column(Text)
