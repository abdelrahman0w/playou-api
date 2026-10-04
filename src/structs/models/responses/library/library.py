from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from pydantic import Field

from src.structs.enums import ImportStatuses
from src.structs.enums import Platforms
from src.structs.enums import PlaylistKinds
from src.structs.enums import RemovedBy


class TrackSource(BaseModel):
    platform: Platforms
    platform_id: str
    url: str | None = None
    embed_blocked: bool = False


class CatalogTrack(BaseModel):
    id: UUID
    title: str
    artists: list[str] = Field(default_factory=list)
    album: str | None = None
    duration_ms: int | None = None
    isrc: str | None = None
    explicit: bool | None = None
    artwork_url: str | None = None
    sources: list[TrackSource] = Field(default_factory=list)


class LikedTrack(BaseModel):
    track: CatalogTrack
    liked_at: datetime
    removed_at: datetime | None = None
    removed_by: RemovedBy | None = None


class PlaylistLink(BaseModel):
    platform: Platforms
    platform_playlist_id: str


class Playlist(BaseModel):
    id: UUID
    kind: PlaylistKinds = PlaylistKinds.OWNED
    name: str
    description: str | None = None
    owner_name: str | None = None
    cover_url: str | None = None
    url: str | None = None
    item_count: int = 0
    links: list[PlaylistLink] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    removed_at: datetime | None = None
    removed_by: RemovedBy | None = None


class PlaylistItem(BaseModel):
    track: CatalogTrack
    position: int
    added_at: datetime
    removed_at: datetime | None = None
    removed_by: RemovedBy | None = None


class PlaylistDetail(Playlist):
    items: list[PlaylistItem] = Field(default_factory=list)


class PlatformData(BaseModel):
    platform: Platforms
    likes: int
    playlists: int


class PushPreferences(BaseModel):
    platform: Platforms
    push_likes: bool
    push_playlists: bool


class Progress(BaseModel):
    done: int
    total: int


class ImportProgress(BaseModel):
    likes: Progress | None = None
    playlists: Progress | None = None


class AccountSync(BaseModel):
    platform: Platforms
    status: ImportStatuses
    imported_at: datetime | None = None
    error: str | None = None
    progress: ImportProgress | None = None
