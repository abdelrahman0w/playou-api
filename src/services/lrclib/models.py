from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


class LrclibRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    track_name: str = Field(default="", alias="trackName")
    artist_name: str = Field(default="", alias="artistName")
    duration: float | None = None
    instrumental: bool = False
    plain: str | None = Field(default=None, alias="plainLyrics")
    synced: str | None = Field(default=None, alias="syncedLyrics")
