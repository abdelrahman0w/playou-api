from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from pydantic import Field

from src.structs.enums import CopyScopes
from src.structs.enums import CopyStatuses
from src.structs.enums import ImportStatuses
from src.structs.enums import Platforms
from src.structs.enums import PlaylistImports
from src.structs.enums import PlaylistKinds
from src.structs.enums import RemovedBy
from src.structs.enums import TogetherEffects


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
    thumbnail_url: str | None = None
    sources: list[TrackSource] = Field(default_factory=list)


class LikedTrack(BaseModel):
    track: CatalogTrack
    liked_at: datetime
    removed_at: datetime | None = None
    removed_by: RemovedBy | None = None


class PlaylistLink(BaseModel):
    platform: Platforms
    platform_playlist_id: str
    importing: PlaylistImports = PlaylistImports.AUTO


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
    imported_from: Platforms | None = None
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
    keep_in_sync: bool | None = None


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


class CopyProgress(BaseModel):
    id: UUID
    platform: Platforms
    scope: CopyScopes
    playlist_id: UUID | None = None
    playlist_name: str | None = None
    status: CopyStatuses
    total: int
    pending: int
    missing: int
    resume_at: datetime | None = None
    created_at: datetime
    finished_at: datetime | None = None
    dismissed_at: datetime | None = None
    auto: bool = False


class CopyEstimate(BaseModel):
    scope: CopyScopes
    songs: int
    to_find: int
    days: int


class MissingTracks(BaseModel):
    platform: Platforms
    tracks: list[CatalogTrack] = Field(default_factory=list)


class TogetherTracks(BaseModel):
    tracks: dict[UUID, TogetherEffects] = Field(default_factory=dict)
