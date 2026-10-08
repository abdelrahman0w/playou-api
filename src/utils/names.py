import re
import unicodedata


NAME_LENGTH = 95
MARKS_IN_A_ROW = 3
ZERO_WIDTH_NON_JOINER = "‌"
SELECTORS = {*range(0xFE00, 0xFE10), *range(0xE0100, 0xE01F0)}
SPACES = re.compile(r"\s+")


class InvalidNameError(ValueError):
    pass


def _refused(character: str) -> bool:
    category = unicodedata.category(character)

    return (
        character == "@"
        or ord(character) in SELECTORS
        or category == "Me"
        or category.startswith("S")
        or category in {"Zl", "Zp"}
        or (category.startswith("C") and character != ZERO_WIDTH_NON_JOINER)
    )


def clean_name(raw: str) -> str:
    name = SPACES.sub(" ", unicodedata.normalize("NFC", raw)).strip()
    if not name:
        raise InvalidNameError("A name can't be empty")
    if len(name) > NAME_LENGTH:
        raise InvalidNameError(f"A name can be up to {NAME_LENGTH} characters")
    if any(_refused(character) for character in name):
        raise InvalidNameError(
            "A name can use letters, numbers and punctuation, no emoji or symbols",
        )
    if not any(unicodedata.category(character)[0] in "LN" for character in name):
        raise InvalidNameError("A name needs a letter or a number")

    marks = 0
    for character in name:
        marks = marks + 1 if unicodedata.category(character) in {"Mn", "Mc"} else 0
        if marks > MARKS_IN_A_ROW:
            raise InvalidNameError("A name can't stack that many marks")

    return name
