from pydantic import BaseModel
from pydantic import Field

from src.structs.enums import Platforms
from src.structs.enums import SearchStatuses
from src.structs.models.responses.library import CatalogTrack


class PlatformSearchResult(BaseModel):
    platform: Platforms
    status: SearchStatuses
    tracks: list[CatalogTrack] = Field(default_factory=list)


class SearchResults(BaseModel):
    query: str
    platforms: list[PlatformSearchResult] = Field(default_factory=list)
