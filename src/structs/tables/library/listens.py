from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime
from sqlalchemy import Enum
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import Uuid
from sqlalchemy import text
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column

from src.structs.enums import Platforms
from src.structs.tables.base import Base


def _values(
    enum: type[Platforms],
) -> list[str]:
    return [member.value for member in enum]


class Listen(Base):
    __tablename__ = "listens"
    __table_args__ = (
        Index(None, "user_id", "played_at"),
        Index(None, "track_id"),
        Index(None, "played_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("uuidv7()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
    )
    track_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tracks.id", ondelete="CASCADE"),
    )
    platform: Mapped[Platforms] = mapped_column(
        Enum(Platforms, native_enum=False, length=32, values_callable=_values),
    )
    played_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
