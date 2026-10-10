from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger
from sqlalchemy import DateTime
from sqlalchemy import Enum
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import UniqueConstraint
from sqlalchemy import Uuid
from sqlalchemy import text
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column

from src.structs.enums import ShareSubjects
from src.structs.tables.base import Base


def _values(
    enum: type[ShareSubjects],
) -> list[str]:
    return [member.value for member in enum]


class Share(Base):
    __tablename__ = "shares"
    __table_args__ = (
        UniqueConstraint("code"),
        Index(None, "user_id", "created_at"),
        Index(None, "track_id"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("uuidv7()"),
    )
    code: Mapped[str] = mapped_column(String(16))
    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
    )
    subject: Mapped[ShareSubjects] = mapped_column(
        Enum(ShareSubjects, native_enum=False, length=32, values_callable=_values),
    )
    track_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("tracks.id", ondelete="CASCADE"),
    )
    anonymous_opens: Mapped[int] = mapped_column(
        Integer,
        server_default=text("0"),
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ShareOpen(Base):
    __tablename__ = "share_opens"
    __table_args__ = (
        UniqueConstraint("share_id", "user_id"),
        Index(None, "user_id", "last_opened_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    share_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("shares.id", ondelete="CASCADE"),
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
    )
    opens: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    first_opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
