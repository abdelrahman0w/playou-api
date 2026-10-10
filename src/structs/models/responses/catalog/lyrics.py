from pydantic import BaseModel
from pydantic import Field

from src.structs.enums import LyricsStatuses


class LyricsLine(BaseModel):
    at_ms: int
    text: str


class Lyrics(BaseModel):
    status: LyricsStatuses
    lines: list[LyricsLine] = Field(default_factory=list)
    plain: str | None = None
    source: str | None = None
    reported: bool = False
