from typing import Self
from uuid import UUID

from pydantic import BaseModel
from pydantic import Field
from pydantic import model_validator


class PlayRequest(BaseModel):
    device_id: str | None = Field(default=None, max_length=255)
    track_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=100)
    playlist_id: UUID | None = None
    offset: int = Field(default=0, ge=0)
    position_ms: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def one_thing_to_play(self) -> Self:
        if (self.track_ids is None) == (self.playlist_id is None):
            raise ValueError("Play either tracks or a playlist")

        return self


class RejectedTokenRequest(BaseModel):
    rejected: str = Field(min_length=1, max_length=4096)
