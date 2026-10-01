from src.exceptions import AppError
from src.exceptions import PlatformReconnectRequiredError
from src.settings import settings
from src.utils import DecryptionError
from src.utils import decrypt
from src.utils import encrypt


def _keys() -> list[str]:
    keys = [key.get_secret_value() for key in settings.encryption.keys]
    if not keys:
        raise AppError(
            "ENCRYPTION_KEYS is not set, so tokens cannot be stored",
        )

    return keys


def seal(value: str) -> str:
    return encrypt(value, _keys())


def unseal(value: str) -> str:
    try:
        return decrypt(value, _keys())
    except DecryptionError as exc:
        raise PlatformReconnectRequiredError(
            "The account's tokens cannot be read, link it again",
        ) from exc
