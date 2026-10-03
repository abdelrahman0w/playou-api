from datetime import datetime

from pydantic import BaseModel


class PlaybackToken(BaseModel):
    access_token: str
    expires_at: datetime | None = None
