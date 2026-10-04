from datetime import datetime

from pydantic import BaseModel
from pydantic import Field

from src.structs.enums import Platforms
from src.structs.models.responses.library import CatalogTrack


class PlaybackToken(BaseModel):
    access_token: str
    expires_at: datetime | None = None


class PlaybackSession(BaseModel):
    device_id: str
    device_name: str
    platform: Platforms
    source: str | None = None
    tracks: list[CatalogTrack] = Field(default_factory=list)
    cursor: int = 0
    current: CatalogTrack | None = None
    up_next: list[CatalogTrack] = Field(default_factory=list)
    playing: bool = False
    position_ms: int = 0
    position_at: datetime
    version: int


class PlaybackSessionSaved(BaseModel):
    version: int
    position_at: datetime
