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
from sqlalchemy import Text
from sqlalchemy import UniqueConstraint
from sqlalchemy import Uuid
from sqlalchemy import text
from sqlalchemy import true
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column

from src.structs.enums import Platforms
from src.structs.tables.base import Base


def _values(enum: type[Platforms]) -> list[str]:
    return [member.value for member in enum]


class LinkedAccount(Base):
    __tablename__ = "linked_accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "platform"),
        Index(None, "refresh_expires_at"),
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
    reconnect_required_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    external_id: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(255))
    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refresh_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    expiry_warned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    disconnect_warned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    likes_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    likes_total: Mapped[int | None] = mapped_column(Integer)
    push_likes: Mapped[bool] = mapped_column(Boolean, server_default=true())
    push_playlists: Mapped[bool] = mapped_column(Boolean, server_default=true())
