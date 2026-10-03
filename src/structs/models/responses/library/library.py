from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from pydantic import Field

from src.structs.enums import Platforms
from src.structs.enums import RemovedBy


class TrackSource(BaseModel):
    platform: Platforms
    platform_id: str
    url: str | None = None


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
    name: str
    description: str | None = None
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


class PushPreferences(BaseModel):
    platform: Platforms
    push_likes: bool
    push_playlists: bool
