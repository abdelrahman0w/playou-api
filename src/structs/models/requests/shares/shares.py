from uuid import UUID

from pydantic import BaseModel
from pydantic import Field


class ShareRequest(BaseModel):
    track_id: UUID


class ShareListRequest(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)
