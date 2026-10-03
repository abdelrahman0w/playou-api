from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import SecretStr

from src.structs.enums import AccountStatuses
from src.structs.enums import Platforms
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


class PlatformPlaylist(BaseModel):
    platform_id: str
    snapshot_id: str | None = None


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
    status: AccountStatuses
    external_id: str
    display_name: str | None = None
    access_token: str
    refresh_token: str | None = None
    expires_at: datetime | None = None
    refresh_expires_at: datetime | None = None
    expiry_warned_at: datetime | None = None
    scopes: list[str] = Field(default_factory=list)
    push_likes: bool = True
    push_playlists: bool = True
    created_at: datetime
    updated_at: datetime


class ExpiringAccount(BaseModel):
    account: StoredAccount
    owner: AccountOwner


class LikeSyncState(BaseModel):
    liked: bool
    platform_id: str | None = None


class PlaylistSyncState(BaseModel):
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
