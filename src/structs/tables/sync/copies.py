from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger
from sqlalchemy import Boolean
from sqlalchemy import DateTime
from sqlalchemy import Enum
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import UniqueConstraint
from sqlalchemy import Uuid
from sqlalchemy import false
from sqlalchemy import text
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column

from src.structs.enums import CopyItemStatuses
from src.structs.enums import CopyScopes
from src.structs.enums import CopyStatuses
from src.structs.enums import Platforms
from src.structs.tables.base import Base


def _values(
    enum: type[Platforms]
    | type[CopyScopes]
    | type[CopyStatuses]
    | type[CopyItemStatuses],
) -> list[str]:
    return [member.value for member in enum]


class Copy(Base):
    __tablename__ = "copies"
    __table_args__ = (
        Index(
            None,
            "user_id",
            "platform",
            "scope",
            "playlist_id",
            unique=True,
            postgresql_where=text("status = 'RUNNING'"),
            postgresql_nulls_not_distinct=True,
        ),
        Index(None, "status", "resume_at"),
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
    platform: Mapped[Platforms] = mapped_column(
        Enum(Platforms, native_enum=False, length=32, values_callable=_values),
    )
    scope: Mapped[CopyScopes] = mapped_column(
        Enum(CopyScopes, native_enum=False, length=32, values_callable=_values),
    )
    playlist_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("playlists.id", ondelete="CASCADE"),
    )
    status: Mapped[CopyStatuses] = mapped_column(
        Enum(CopyStatuses, native_enum=False, length=32, values_callable=_values),
    )
    total: Mapped[int] = mapped_column(Integer, default=0)
    resume_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auto: Mapped[bool] = mapped_column(Boolean, server_default=false())


class CopyItem(Base):
    __tablename__ = "copy_items"
    __table_args__ = (
        UniqueConstraint("copy_id", "track_id"),
        Index(None, "track_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    copy_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("copies.id", ondelete="CASCADE"),
    )
    track_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tracks.id", ondelete="CASCADE"),
    )
    status: Mapped[CopyItemStatuses] = mapped_column(
        Enum(CopyItemStatuses, native_enum=False, length=32, values_callable=_values),
    )
