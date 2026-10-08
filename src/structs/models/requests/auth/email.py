from typing import Literal

from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator

from src.structs.enums import SessionTransports
from src.utils.names import clean_name


EMAIL = r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$"


class EmailCodeRequest(BaseModel):
    email: str = Field(max_length=320, pattern=EMAIL)
    locale: Literal["en", "ar"] = "en"

    @field_validator("email", mode="before")
    @classmethod
    def normalize(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


class EmailVerifyRequest(EmailCodeRequest):
    code: str = Field(pattern=r"^\d{6}$")
    transport: SessionTransports = SessionTransports.COOKIE
    name: str | None = None

    @field_validator("name")
    @classmethod
    def cleaned(cls, value: str | None) -> str | None:
        return clean_name(value) if value is not None else None
