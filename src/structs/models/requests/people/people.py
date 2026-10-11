from pydantic import BaseModel
from pydantic import Field


class PeopleSearchRequest(BaseModel):
    q: str = Field(min_length=1, max_length=60)


class PeoplePageRequest(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)


class OnProfileRequest(BaseModel):
    on_profile: bool
