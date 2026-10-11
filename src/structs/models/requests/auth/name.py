from pydantic import BaseModel
from pydantic import field_validator

from src.utils.names import clean_name
from src.utils.usernames import clean_username


class NameRequest(BaseModel):
    name: str | None = None
    username: str | None = None
    searchable: bool | None = None
    private: bool | None = None

    @field_validator("name")
    @classmethod
    def cleaned(cls, value: str | None) -> str | None:
        return clean_name(value) if value is not None else None

    @field_validator("username")
    @classmethod
    def cleaned_username(cls, value: str | None) -> str | None:
        return clean_username(value) if value is not None else None
