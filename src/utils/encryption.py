from collections.abc import Sequence
from functools import cache

from cryptography.fernet import Fernet
from cryptography.fernet import InvalidToken
from cryptography.fernet import MultiFernet


class DecryptionError(Exception):
    pass


def make_key() -> str:
    return Fernet.generate_key().decode()


@cache
def _cipher(keys: tuple[str, ...]) -> MultiFernet:
    if not keys:
        raise ValueError("At least one key is needed")

    return MultiFernet([Fernet(key) for key in keys])


def encrypt(value: str, keys: Sequence[str]) -> str:
    return _cipher(tuple(keys)).encrypt(value.encode()).decode()


def decrypt(value: str, keys: Sequence[str]) -> str:
    try:
        return _cipher(tuple(keys)).decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise DecryptionError("None of the keys decrypts the value") from exc
