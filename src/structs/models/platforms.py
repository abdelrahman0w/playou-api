import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import SecretStr
from pydantic import field_validator

from src.structs.enums import AccountStatuses
from src.structs.enums import Platforms
from src.structs.enums import PlaylistImports
from src.structs.enums import PlaylistKinds
from src.structs.enums import SyncSubjects


ISRC = re.compile(r"[A-Z]{2}[A-Z0-9]{3}\d{7}")


class Capabilities(BaseModel):
    model_config = ConfigDict(frozen=True)

    search: bool = False
    search_on_demand: bool = False
    search_shared: bool = False
    search_isrc: bool = False
    copy_to: bool = False
    copy_likes: bool = False
    find_cost: int = 0
    write_cost: int = 0
    daily_find_units: int | None = None
    daily_write_units: int | None = None
    push_by_default: bool = True
    like: bool = False
    playlists_read: bool = False
    playlists_write: bool = False
    playlist_remove: bool = False
    playback: bool = False


class PlatformTokens(BaseModel):
    access_token: SecretStr
    refresh_token: SecretStr | None = None
    expires_in_seconds: int | None = None
    refresh_expires_in_seconds: int | None = None
    scopes: list[str] = Field(default_factory=list)


class PlatformProfile(BaseModel):
    external_id: str
    display_name: str | None = None


class Track(BaseModel):
    platform: Platforms
    platform_id: str
    title: str
    artists: list[str] = Field(default_factory=list)
    album: str | None = None
    duration_ms: int | None = None
    isrc: str | None = None
    explicit: bool | None = None
    artwork_url: str | None = None
    url: str | None = None

    @field_validator("isrc", mode="before")
    @classmethod
    def normalize_isrc(cls, value: object) -> object:
        if not isinstance(value, str):
            return value

        isrc = re.sub(r"[\s-]", "", value).upper()

        return isrc if ISRC.fullmatch(isrc) else None


class DuplicateTrack(BaseModel):
    keep: UUID
    drop: UUID
    title: str
    duplicate_title: str


class SavedTrack(BaseModel):
    track: Track
    added_at: datetime | None = None
    ignored: bool = False


class SavedTracksPage(BaseModel):
    total: int
    items: list[SavedTrack] = Field(default_factory=list)
    next: str | None = None


class RemotePlaylist(BaseModel):
    platform_id: str
    name: str
    description: str | None = None
    owner_id: str | None = None
    owner_name: str | None = None
    collaborative: bool = False
    owned: bool | None = None
    snapshot_id: str | None = None
    cover_url: str | None = None
    url: str | None = None


class PlaybackDevice(BaseModel):
    id: str
    name: str
    type: str
    is_active: bool = False
    is_restricted: bool = False
    volume_percent: int | None = None


class PlaybackRequest(BaseModel):
    device_id: str | None = None
    track_ids: list[str] = Field(default_factory=list)
    playlist_id: str | None = None
    offset_track_id: str | None = None
    position_ms: int = 0


class PlatformPlaylist(BaseModel):
    platform_id: str
    snapshot_id: str | None = None


class PlaylistTracks(BaseModel):
    tracks: list[Track] = Field(default_factory=list)
    music: bool = True


class LinkedPlaylist(BaseModel):
    playlist_id: UUID
    kind: PlaylistKinds
    snapshot_id: str | None = None
    removed: bool
    skipped: bool = False
    importing: PlaylistImports = PlaylistImports.AUTO


class PendingLink(BaseModel):
    user_id: UUID
    platform: Platforms
    verifier: str


class AccountOwner(BaseModel):
    email: str
    locale: str


class StoredAccount(BaseModel):
    id: UUID
    user_id: UUID
    platform: Platforms
    external_id: str
    display_name: str | None = None
    access_token: str
    refresh_token: str | None = None
    expires_at: datetime | None = None
    refresh_expires_at: datetime | None = None
    expiry_warned_at: datetime | None = None
    disconnect_warned_at: datetime | None = None
    reconnect_required_at: datetime | None = None
    imported_at: datetime | None = None
    likes_read_at: datetime | None = None
    likes_total: int | None = None
    scopes: list[str] = Field(default_factory=list)
    push_likes: bool = True
    push_playlists: bool = True
    keep_in_sync: bool | None = None
    synced_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    def status_at(self, now: datetime) -> AccountStatuses:
        expired = self.refresh_expires_at is not None and self.refresh_expires_at <= now
        if self.reconnect_required_at is not None or expired:
            return AccountStatuses.NEEDS_RECONNECT

        return AccountStatuses.ACTIVE


class ExpiringAccount(BaseModel):
    account: StoredAccount
    owner: AccountOwner


class LikeSyncState(BaseModel):
    liked: bool
    platform_id: str | None = None


class PlaylistSyncState(BaseModel):
    kind: PlaylistKinds = PlaylistKinds.OWNED
    name: str
    description: str | None = None
    removed: bool
    skipped: bool = False
    link: PlatformPlaylist | None = None
    platform_ids: list[str] = Field(default_factory=list)
    removed_platform_ids: list[str] = Field(default_factory=list)


class SyncTask(BaseModel):
    id: int
    user_id: UUID
    platform: Platforms
    subject: SyncSubjects
    subject_id: UUID
    attempts: int
    requests: int | None = None


class StoredPlaybackSession(BaseModel):
    user_id: UUID
    device_id: str
    device_name: str
    platform: Platforms
    source: str | None = None
    track_ids: list[UUID] = Field(default_factory=list)
    cursor: int = 0
    current_track_id: UUID | None = None
    up_next: list[UUID] = Field(default_factory=list)
    playing: bool = False
    position_ms: int = 0
    position_at: datetime
    version: int
