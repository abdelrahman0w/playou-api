from pydantic import BaseModel
from pydantic import Field

from src.structs.enums import ErrorTypes


class Page[T](BaseModel):
    items: list[T] = Field(default_factory=list)
    page: int | None = None
    page_size: int | None = None
    total_count: int | None = None
    total_pages: int | None = None


class ErrorDetail(BaseModel):
    type: ErrorTypes
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
