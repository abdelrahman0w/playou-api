from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from pydantic import Field

from src.structs.models.responses.library import CatalogTrack
from src.structs.models.responses.shares import SharedPlaylist


class MessageReaction(BaseModel):
    emoji: str
    mine: bool


class ChatMessage(BaseModel):
    id: UUID
    mine: bool
    text: str | None = None
    track: CatalogTrack | None = None
    playlist: SharedPlaylist | None = None
    unsent: bool = False
    via_link: bool = False
    reactions: list[MessageReaction] = Field(default_factory=list)
    created_at: datetime


class ConversationSummary(BaseModel):
    id: UUID
    name: str | None = None
    username: str | None = None
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


class MessagePerson(BaseModel):
    username: str
    name: str
    chat_id: UUID | None = None


class StartedChat(BaseModel):
    conversation_id: UUID
    message: ChatMessage
