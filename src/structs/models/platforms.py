from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import SecretStr

from src.structs.enums import AccountStatuses
from src.structs.enums import Platforms
from src.structs.enums import PlaylistKinds
from src.structs.enums import SyncSubjects


class Capabilities(BaseModel):
    model_config = ConfigDict(frozen=True)

    search: bool = False
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


class SavedTrack(BaseModel):
    track: Track
    added_at: datetime | None = None


class SavedTracksPage(BaseModel):
    total: int
    items: list[SavedTrack] = Field(default_factory=list)
    has_more: bool = False


class RemotePlaylist(BaseModel):
    platform_id: str
    name: str
    description: str | None = None
    owner_id: str | None = None
    owner_name: str | None = None
    collaborative: bool = False
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


class LinkedPlaylist(BaseModel):
    playlist_id: UUID
    kind: PlaylistKinds
    snapshot_id: str | None = None
    removed: bool


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
