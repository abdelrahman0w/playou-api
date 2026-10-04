from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator


class SearchRequest(BaseModel):
    q: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=20, ge=1, le=50)
    everywhere: bool = False

    @field_validator("q", mode="before")
    @classmethod
    def normalize(cls, value: object) -> object:
        return " ".join(value.split()) if isinstance(value, str) else value
