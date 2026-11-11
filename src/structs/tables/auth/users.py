from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger
from sqlalchemy import Boolean
from sqlalchemy import DateTime
from sqlalchemy import Enum
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import Uuid
from sqlalchemy import false
from sqlalchemy import func
from sqlalchemy import text
from sqlalchemy import true
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column

from src.structs.enums import NameFields
from src.structs.tables.base import Base


def _values(enum: type[NameFields]) -> list[str]:
    return [member.value for member in enum]


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("uq_users_username", func.lower(text("username")), unique=True),
        Index(
            "ix_users_username_search",
            text("lower(username) gin_trgm_ops"),
            postgresql_using="gin",
        ),
        Index(
            "ix_users_name_search",
            text("lower(name) gin_trgm_ops"),
            postgresql_using="gin",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("uuidv7()"),
    )
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(95))
    username: Mapped[str] = mapped_column(String(30))
    searchable: Mapped[bool] = mapped_column(Boolean, server_default=true())
    private: Mapped[bool] = mapped_column(Boolean, server_default=false())
    locale: Mapped[str] = mapped_column(String(8), default="en")
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sign_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (Index(None, "user_id", "expires_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(Text)


class AuthEmailCode(Base):
    __tablename__ = "auth_email_codes"
    __table_args__ = (Index(None, "email", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(String(320))
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NameChange(Base):
    __tablename__ = "name_changes"
    __table_args__ = (Index(None, "user_id", "changed_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
    )
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    field: Mapped[NameFields] = mapped_column(
        Enum(NameFields, native_enum=False, length=16, values_callable=_values),
        server_default=NameFields.NAME.value,
    )
