from datetime import datetime
from uuid import UUID

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
from sqlalchemy import false
from sqlalchemy import text
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column

from src.structs.enums import Platforms
from src.structs.enums import PlaylistImports
from src.structs.enums import PlaylistKinds
from src.structs.enums import RemovedBy
from src.structs.tables.base import Base


def _values(
    enum: type[RemovedBy]
    | type[Platforms]
    | type[PlaylistKinds]
    | type[PlaylistImports],
) -> list[str]:
    return [member.value for member in enum]


class Playlist(Base):
    __tablename__ = "playlists"
    __table_args__ = (Index(None, "user_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("uuidv7()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
    )
    kind: Mapped[PlaylistKinds] = mapped_column(
        Enum(
            PlaylistKinds,
            native_enum=False,
            length=32,
            values_callable=_values,
        ),
        server_default=PlaylistKinds.OWNED.value,
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    owner_name: Mapped[str | None] = mapped_column(String(255))
    cover_url: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    imported_from: Mapped[Platforms | None] = mapped_column(
        Enum(
            Platforms,
            native_enum=False,
            length=32,
            values_callable=_values,
        ),
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_by: Mapped[RemovedBy | None] = mapped_column(
        Enum(
            RemovedBy,
            native_enum=False,
            length=32,
            values_callable=_values,
        ),
    )
    on_profile: Mapped[bool] = mapped_column(Boolean, server_default=false())
    pinned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    library_position: Mapped[int | None] = mapped_column(Integer)


class PlaylistItem(Base):
    __tablename__ = "playlist_items"
    __table_args__ = (
        UniqueConstraint("playlist_id", "track_id"),
        Index(None, "playlist_id", "position"),
        Index(None, "track_id"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("uuidv7()"),
    )
    playlist_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("playlists.id", ondelete="CASCADE"),
    )
    track_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tracks.id", ondelete="CASCADE"),
    )
    position: Mapped[int] = mapped_column(Integer)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_by: Mapped[RemovedBy | None] = mapped_column(
        Enum(RemovedBy, native_enum=False, length=32, values_callable=_values),
    )


class PlaylistLink(Base):
    __tablename__ = "playlist_links"
    __table_args__ = (
        UniqueConstraint("playlist_id", "platform"),
        UniqueConstraint("user_id", "platform", "platform_playlist_id"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=text("uuidv7()"),
    )
    playlist_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("playlists.id", ondelete="CASCADE"),
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
    )
    platform: Mapped[Platforms] = mapped_column(
        Enum(Platforms, native_enum=False, length=32, values_callable=_values),
    )
    platform_playlist_id: Mapped[str] = mapped_column(String(255))
    snapshot_id: Mapped[str | None] = mapped_column(Text)
    importing: Mapped[PlaylistImports] = mapped_column(
        Enum(PlaylistImports, native_enum=False, length=32, values_callable=_values),
        default=PlaylistImports.AUTO,
        server_default=PlaylistImports.AUTO.value,
    )
