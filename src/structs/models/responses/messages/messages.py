from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from pydantic import Field

from src.structs.models.responses.library import CatalogTrack


class ChatMessage(BaseModel):
    id: UUID
    mine: bool
    text: str | None = None
    track: CatalogTrack | None = None
    unsent: bool = False
    via_link: bool = False
    created_at: datetime


class ConversationSummary(BaseModel):
    id: UUID
    name: str | None = None
    last_message: ChatMessage | None = None
    unread: int = 0
    blocked: bool = False
    can_send: bool = True
    last_message_at: datetime | None = None


class Conversation(ConversationSummary):
    messages: list[ChatMessage] = Field(default_factory=list)
    more: bool = False


class MessageUpdates(BaseModel):
    tag: str
    unread: int


class PushSettings(BaseModel):
    enabled: bool
    public_key: str | None = None
