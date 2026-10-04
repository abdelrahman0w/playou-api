from pydantic import BaseModel
from pydantic import Field


class ChooseSimilarRequest(BaseModel):
    platform_id: str | None = Field(default=None, min_length=1, max_length=255)
