from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger
from sqlalchemy import Computed
from sqlalchemy import DateTime
from sqlalchemy import Enum
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import Text
from sqlalchemy import Uuid
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column

from src.structs.enums import Platforms
from src.structs.enums import SyncOutcomes
from src.structs.enums import SyncStatuses
from src.structs.enums import SyncSubjects
from src.structs.tables.base import Base


def _values(
    enum: type[Platforms]
    | type[SyncOutcomes]
    | type[SyncStatuses]
    | type[SyncSubjects],
) -> list[str]:
    return [member.value for member in enum]


class SyncOperation(Base):
    __tablename__ = "sync_operations"
    __table_args__ = (
        Index(
            None,
            "user_id",
            "platform",
            "subject",
            "subject_id",
            unique=True,
            postgresql_where=text("status = 'PENDING'"),
        ),
        Index(
            None,
            "next_attempt_at",
            postgresql_where=text("status = 'PENDING'"),
        ),
        Index(None, "user_id", "subject", "subject_id", "id"),
        Index(
            None,
            "finished_at",
            postgresql_where=text("status <> 'PENDING'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
    )
    platform: Mapped[Platforms] = mapped_column(
        Enum(Platforms, native_enum=False, length=32, values_callable=_values),
    )
    subject: Mapped[SyncSubjects] = mapped_column(
        Enum(SyncSubjects, native_enum=False, length=32, values_callable=_values),
    )
    subject_id: Mapped[UUID] = mapped_column(Uuid)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    progress: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[SyncOutcomes | None] = mapped_column(
        Enum(SyncOutcomes, native_enum=False, length=32, values_callable=_values),
    )
    status: Mapped[SyncStatuses] = mapped_column(
        Enum(SyncStatuses, native_enum=False, length=32, values_callable=_values),
        Computed(
            f"CASE WHEN finished_at IS NULL THEN '{SyncStatuses.PENDING}' "
            "ELSE outcome END",
            persisted=True,
        ),
    )
