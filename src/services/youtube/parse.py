import re

from src.utils.matching import TOPIC
from src.utils.matching import VEVO
from src.utils.matching import clean_title


DASH = re.compile("\\s+[-\u2013\u2014]\\s+")
ARTISTS = re.compile(
    r"\s*(?:,|&|\bx\b|\bfeat\.?|\bft\.?|\bfeaturing)\s*", re.IGNORECASE
)
DURATION = re.compile(r"^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$")


def split_artists(value: str) -> list[str]:
    return [name for name in (part.strip() for part in ARTISTS.split(value)) if name]


def parse_video(title: str, channel: str) -> tuple[str, list[str]]:
    if TOPIC.search(channel):
        return clean_title(title), [TOPIC.sub("", channel).strip()]

    parts = DASH.split(title, maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        return clean_title(parts[1]), split_artists(parts[0])

    return clean_title(title), [VEVO.sub("", channel).strip() or channel]


def duration_ms(value: str | None) -> int | None:
    if not value:
        return None

    match = DURATION.match(value)
    if match is None:
        return None

    days, hours, minutes, seconds = (int(part or 0) for part in match.groups())

    return (((days * 24 + hours) * 60 + minutes) * 60 + seconds) * 1000
