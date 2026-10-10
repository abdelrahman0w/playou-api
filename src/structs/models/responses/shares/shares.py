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


class SharedTrack(BaseModel):
    code: str
    track: CatalogTrack
    created_at: datetime


class ShareOpened(BaseModel):
    track_id: UUID
    shared_by: Sharer


class ShareOpener(BaseModel):
    name: str
    opens: int
    last_opened_at: datetime


class SentShare(BaseModel):
    code: str
    url: str
    track: CatalogTrack
    created_at: datetime
    anonymous_opens: int = 0
    opened_by: list[ShareOpener] = Field(default_factory=list)


class ReceivedShare(BaseModel):
    code: str
    track: CatalogTrack
    shared_by: Sharer
    opened_at: datetime
