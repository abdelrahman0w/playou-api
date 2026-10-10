from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from pydantic import Field

from src.structs.models.responses.library import CatalogTrack


class ShareLink(BaseModel):
    code: str
    url: str


class Sharer(BaseModel):
    name: str


class SharedPlaylist(BaseModel):
    code: str
    name: str
    description: str | None = None
    cover_url: str | None = None
    item_count: int = 0


class Shared(BaseModel):
    code: str
    created_at: datetime
    track: CatalogTrack | None = None
    playlist: SharedPlaylist | None = None
    items: list[CatalogTrack] = Field(default_factory=list)
    more: bool = False


class ShareOpened(BaseModel):
    track_id: UUID | None = None
    playlist: bool = False
    shared_by: Sharer | None = None


class ShareOpener(BaseModel):
    name: str
    opens: int
    last_opened_at: datetime


class SentShare(BaseModel):
    code: str
    url: str
    track: CatalogTrack | None = None
    playlist: SharedPlaylist | None = None
    created_at: datetime
    anonymous_opens: int = 0
    opened_by: list[ShareOpener] = Field(default_factory=list)


class ReceivedShare(BaseModel):
    code: str
    track: CatalogTrack | None = None
    playlist: SharedPlaylist | None = None
    shared_by: Sharer
    opened_at: datetime
