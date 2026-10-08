from pydantic import BaseModel
from pydantic import field_validator

from src.utils.names import clean_name


class NameRequest(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def cleaned(cls, value: str) -> str:
        return clean_name(value)
