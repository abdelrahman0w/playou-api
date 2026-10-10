import secrets
import string

from src.settings import settings


CODE_LENGTH = 8
ALPHABET = string.digits + string.ascii_letters


def new_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def share_url(code: str) -> str:
    return f"{settings.app.web_url.rstrip('/')}/s/{code}"
