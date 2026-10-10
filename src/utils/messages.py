import re
import unicodedata


MESSAGE_LENGTH = 1000
DIRECTION_CONTROLS = frozenset(
    {*map(chr, range(0x202A, 0x202F)), *map(chr, range(0x2066, 0x206A))},
)
KEPT = frozenset({"\n", "‌", "‍"})
NEWLINES = re.compile(r"\n{4,}")


class InvalidMessageError(ValueError):
    pass


def _kept(char: str) -> bool:
    if char in KEPT:
        return True
    if char in DIRECTION_CONTROLS:
        return False

    return not unicodedata.category(char).startswith("C")


def clean_message(raw: str) -> str:
    text = unicodedata.normalize("NFC", raw).replace("\r\n", "\n").replace("\t", " ")
    text = "".join(char for char in text if _kept(char))
    text = NEWLINES.sub("\n\n\n", text).strip()
    if not text:
        raise InvalidMessageError("Write something to send")
    if len(text) > MESSAGE_LENGTH:
        raise InvalidMessageError(f"A message is {MESSAGE_LENGTH} characters at most")

    return text
