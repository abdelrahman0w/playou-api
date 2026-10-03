from pydantic import BaseModel


class OutgoingEmail(BaseModel):
    to: str
    subject: str
    html: str
    text: str
