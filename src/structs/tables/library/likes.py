from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime
from sqlalchemy import Enum
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import UniqueConstraint
from sqlalchemy import Uuid
from sqlalchemy import text
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column

from src.structs.enums import Platforms
from src.structs.enums import RemovedBy
from src.structs.tables.base import Base


def _values(
    enum: type[RemovedBy],
) -> list[str]:
    return [member.value for member in enum]


class Like(Base):
    __tablename__ = "likes"
    __table_args__ = (
        UniqueConstraint("user_id", "track_id"),
        Index(None, "user_id", "liked_at"),
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
    liked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    imported_from: Mapped[Platforms | None] = mapped_column(
        Enum(Platforms, native_enum=False, length=32, values_callable=_values),
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_by: Mapped[RemovedBy | None] = mapped_column(
        Enum(RemovedBy, native_enum=False, length=32, values_callable=_values),
    )
