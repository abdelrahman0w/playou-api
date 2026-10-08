from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AuthUser(BaseModel):
    id: UUID
    email: str
    name: str | None = None
    locale: str
    created_at: datetime
    last_sign_in_at: datetime | None = None
    can_delete_data: bool = True
    name_changes_left: int = 0
    name_change_at: datetime | None = None


class BearerSession(BaseModel):
    user: AuthUser
    token: str
    expires_in_seconds: int


class EmailCodeSent(BaseModel):
    expires_in_seconds: int
    resend_in_seconds: int
