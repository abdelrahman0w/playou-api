from pydantic import BaseModel
from pydantic import Field

from src.structs.enums import Platforms
from src.structs.enums import SearchStatuses
from src.structs.models.platforms import Track


class PlatformSearchResult(BaseModel):
    platform: Platforms
    status: SearchStatuses
    tracks: list[Track] = Field(default_factory=list)


class SearchResults(BaseModel):
    query: str
    platforms: list[PlatformSearchResult] = Field(default_factory=list)
