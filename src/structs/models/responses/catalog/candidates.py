from pydantic import BaseModel

from src.structs.enums import Closeness
from src.structs.enums import Platforms
from src.structs.models.platforms import Track
from src.structs.models.responses.library import CatalogTrack


class Candidate(BaseModel):
    track: Track
    closeness: Closeness


class TrackMatch(BaseModel):
    track: CatalogTrack
    platform: Platforms
    picked: CatalogTrack
