from uuid import UUID

from pydantic import BaseModel
from pydantic import Field

from src.structs.enums import FollowStates
from src.structs.models.responses.library import CatalogTrack


class Person(BaseModel):
    username: str
    name: str
    private: bool = False
    you_follow: FollowStates = FollowStates.NONE
    follows_you: bool = False


class ProfilePlaylist(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    cover_url: str | None = None
    item_count: int = 0


class Profile(Person):
    followers: int = 0
    following: int = 0
    you: bool = False
    blocked: bool = False
    visible: bool = True
    chat_id: UUID | None = None
    can_message: bool = False
    playlists: list[ProfilePlaylist] = Field(default_factory=list)


class ProfilePlaylistSongs(BaseModel):
    playlist: ProfilePlaylist
    items: list[CatalogTrack] = Field(default_factory=list)
    more: bool = False


class UsernameCheck(BaseModel):
    username: str
    available: bool
    reason: str | None = None
