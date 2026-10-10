from typing import Self
from uuid import UUID

from pydantic import BaseModel
from pydantic import Field
from pydantic import model_validator


class ShareRequest(BaseModel):
    track_id: UUID | None = None
    playlist_id: UUID | None = None

    @model_validator(mode="after")
    def one_thing(self) -> Self:
        if (self.track_id is None) == (self.playlist_id is None):
            raise ValueError("Share either a song or a playlist")

        return self


class ShareListRequest(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)
