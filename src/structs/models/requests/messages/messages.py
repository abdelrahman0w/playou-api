from typing import Self
from uuid import UUID

from emoji import is_emoji
from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator

from src.utils.messages import clean_message


class SendMessageRequest(BaseModel):
    text: str | None = Field(default=None, max_length=4000)
    track_id: UUID | None = None
    playlist_id: UUID | None = None

    @field_validator("text")
    @classmethod
    def cleaned(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None

        return clean_message(value)

    @model_validator(mode="after")
    def something_to_send(self) -> Self:
        if self.track_id is not None and self.playlist_id is not None:
            raise ValueError("Send a song or a playlist, not both")
        if self.text is None and self.track_id is None and self.playlist_id is None:
            raise ValueError("Send some text, a song, a playlist, or text with one")

        return self


class ConversationListRequest(BaseModel):
    with_messages: bool = False
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)


class MessageListRequest(BaseModel):
    before: UUID | None = None
    limit: int = Field(default=50, ge=1, le=100)


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=200)
    auth: str = Field(min_length=1, max_length=100)


class PushSubscriptionRequest(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2000, pattern=r"^https://")
    keys: PushKeys


class PushRemovalRequest(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2000)


class MessagePeopleRequest(BaseModel):
    q: str = Field(default="", max_length=60)


EMOJI_STYLE = "\ufe0f"


class ReactionRequest(BaseModel):
    emoji: str = Field(min_length=1, max_length=16)

    @field_validator("emoji")
    @classmethod
    def one_emoji(cls, value: str) -> str:
        if is_emoji(value):
            return value

        plain = value.replace(EMOJI_STYLE, "")
        if plain and is_emoji(plain):
            return plain

        raise ValueError("React with one emoji")
