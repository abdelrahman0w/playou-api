from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator

from src.structs.enums import LikeSorts
from src.structs.enums import Platforms
from src.structs.enums import PlaylistImports
from src.structs.enums import PlaylistKinds
from src.structs.enums import PlaylistSorts


def _trimmed(value: object) -> object:
    return value.strip() if isinstance(value, str) else value


class LibraryListRequest(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)
    include_removed: bool = False
    platform: Platforms | None = None
    q: str | None = Field(default=None, max_length=100)

    @field_validator("q", mode="before")
    @classmethod
    def blank_is_none(cls, value: object) -> object:
        value = _trimmed(value)

        return value or None


class LikeListRequest(LibraryListRequest):
    sort: LikeSorts = LikeSorts.RECENT


class PlaylistListRequest(LibraryListRequest):
    kind: PlaylistKinds | None = None
    skipped: bool = False
    sort: PlaylistSorts = PlaylistSorts.RECENT


class PlaylistImportingRequest(BaseModel):
    importing: Literal[PlaylistImports.ALWAYS, PlaylistImports.NEVER]


class CreatePlaylistRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=300)

    _trim = field_validator("name", "description", mode="before")(_trimmed)


class UpdatePlaylistRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=300)

    _trim = field_validator("name", "description", mode="before")(_trimmed)


class PlaylistItemsRequest(BaseModel):
    track_ids: list[UUID] = Field(min_length=1, max_length=100)


class PushPreferencesRequest(BaseModel):
    push_likes: bool | None = None
    push_playlists: bool | None = None
