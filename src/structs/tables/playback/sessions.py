from datetime import datetime
from uuid import UUID

from sqlalchemy import ARRAY
from sqlalchemy import Boolean
from sqlalchemy import DateTime
from sqlalchemy import Enum
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column

from src.structs.enums import Platforms
from src.structs.tables.base import Base


def _values(enum: type[Platforms]) -> list[str]:
    return [member.value for member in enum]


class PlaybackSession(Base):
    __tablename__ = "playback_sessions"
    __table_args__ = (Index(None, "updated_at"),)

    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    device_id: Mapped[str] = mapped_column(String(64))
    device_name: Mapped[str] = mapped_column(String(100))
    platform: Mapped[Platforms] = mapped_column(
        Enum(Platforms, native_enum=False, length=32, values_callable=_values),
    )
    source: Mapped[str | None] = mapped_column(String(255))
    track_ids: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid), default=list)
    cursor: Mapped[int] = mapped_column(Integer, default=0)
    current_track_id: Mapped[UUID | None] = mapped_column(Uuid)
    up_next: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid), default=list)
    playing: Mapped[bool] = mapped_column(Boolean, default=False)
    position_ms: Mapped[int] = mapped_column(Integer, default=0)
    position_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)
