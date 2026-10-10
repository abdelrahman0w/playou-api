from datetime import datetime

from pydantic import BaseModel
from pydantic import Field


class SpotifyToken(BaseModel):
    access_token: str
    refresh_token: str | None = None
    expires_in: int | None = None
    refresh_token_expires_in: int | None = None
    scope: str = ""


class SpotifyTokenError(BaseModel):
    error: str
    error_description: str | None = None


class SpotifyErrorDetail(BaseModel):
    message: str | None = None
    reason: str | None = None


class SpotifyError(BaseModel):
    error: SpotifyErrorDetail


class SpotifyUser(BaseModel):
    id: str
    display_name: str | None = None


class SpotifyNamed(BaseModel):
    name: str | None = None


class SpotifyImage(BaseModel):
    url: str
    width: int | None = None


class SpotifyAlbum(BaseModel):
    name: str
    images: list[SpotifyImage] = Field(default_factory=list)


class SpotifyExternalIds(BaseModel):
    isrc: str | None = None


class SpotifyExternalUrls(BaseModel):
    spotify: str | None = None


class SpotifyTrack(BaseModel):
    id: str
    name: str | None = None
    type: str = "track"
    artists: list[SpotifyNamed] = Field(default_factory=list)
    album: SpotifyAlbum | None = None
    duration_ms: int | None = None
    explicit: bool | None = None
    external_ids: SpotifyExternalIds = Field(default_factory=SpotifyExternalIds)
    external_urls: SpotifyExternalUrls = Field(default_factory=SpotifyExternalUrls)


class SpotifyTrackPage(BaseModel):
    items: list[SpotifyTrack | None] = Field(default_factory=list)


class SpotifySearch(BaseModel):
    tracks: SpotifyTrackPage = Field(default_factory=SpotifyTrackPage)


class SpotifyPlaylist(BaseModel):
    id: str
    snapshot_id: str | None = None


class SpotifySnapshot(BaseModel):
    snapshot_id: str | None = None


class SpotifyPlaylistEntryItem(BaseModel):
    id: str | None = None
    type: str | None = None


class SpotifyPlaylistEntry(BaseModel):
    is_local: bool = False
    item: SpotifyPlaylistEntryItem | None = None


class SpotifyPlaylistItems(BaseModel):
    items: list[SpotifyPlaylistEntry] = Field(default_factory=list)
    next: str | None = None


class SpotifySavedTrack(BaseModel):
    added_at: datetime | None = None
    track: SpotifyTrack | None = None


class SpotifySavedTracks(BaseModel):
    total: int = 0
    items: list[SpotifySavedTrack] = Field(default_factory=list)
    next: str | None = None


class SpotifyOwner(BaseModel):
    id: str | None = None
    display_name: str | None = None


class SpotifyUserPlaylist(BaseModel):
    id: str
    name: str = ""
    description: str | None = None
    collaborative: bool = False
    owner: SpotifyOwner = Field(default_factory=SpotifyOwner)
    snapshot_id: str | None = None
    images: list[SpotifyImage] | None = None
    external_urls: SpotifyExternalUrls = Field(default_factory=SpotifyExternalUrls)


class SpotifyUserPlaylists(BaseModel):
    items: list[SpotifyUserPlaylist | None] = Field(default_factory=list)
    next: str | None = None


class SpotifyPlaylistTrackEntry(BaseModel):
    is_local: bool = False
    item: SpotifyTrack | None = None


class SpotifyPlaylistTracks(BaseModel):
    items: list[SpotifyPlaylistTrackEntry] = Field(default_factory=list)
    next: str | None = None


class SpotifyDevice(BaseModel):
    id: str | None = None
    name: str = ""
    type: str = ""
    is_active: bool = False
    is_restricted: bool = False
    volume_percent: int | None = None


class SpotifyDevices(BaseModel):
    devices: list[SpotifyDevice] = Field(default_factory=list)


class SpotifyLinkedFrom(BaseModel):
    id: str | None = None


class SpotifyPlayingItem(BaseModel):
    id: str | None = None
    linked_from: SpotifyLinkedFrom | None = None


class SpotifyPlayer(BaseModel):
    device: SpotifyDevice | None = None
    is_playing: bool = False
    item: SpotifyPlayingItem | None = None
