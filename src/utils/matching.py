import re
import unicodedata


NOISE = re.compile(
    r"\s*[\(\[][^\)\]]*\b("
    r"official|video|audio|lyrics?|visuali[sz]er|hd|hq|4k|remaster(ed)?|clip|mv|"
    r"music video|explicit|clean|radio edit"
    r")\b[^\)\]]*[\)\]]",
    re.IGNORECASE,
)
FEATURING = re.compile(r"\s*[\(\[]?\s*\b(feat\.?|ft\.?|featuring)\s.*$", re.IGNORECASE)
SUFFIX = re.compile(
    "\\s+[-\u2013\u2014]\\s+(\\d{4}\\s+)?remaster(ed)?\\b.*$",
    re.IGNORECASE,
)
SYMBOLS = re.compile(r"[^\w\s]", re.UNICODE)
SPACES = re.compile(r"\s+")
TOPIC = re.compile(r"\s+-\s+topic$", re.IGNORECASE)
VEVO = re.compile(r"vevo$", re.IGNORECASE)

SAME_DURATION_MS = 3_000


def _fold(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def clean_title(title: str) -> str:
    cleaned = NOISE.sub("", title)
    cleaned = SUFFIX.sub("", cleaned)

    return SPACES.sub(" ", cleaned).strip().strip("\"'\u201c\u201d\u2018\u2019").strip()


def normalize_title(title: str) -> str:
    folded = FEATURING.sub("", clean_title(_fold(title)))

    return SPACES.sub(" ", SYMBOLS.sub(" ", folded)).strip()


def normalize_artist(artist: str) -> str:
    folded = VEVO.sub("", TOPIC.sub("", _fold(artist).strip()))

    return SPACES.sub("", SYMBOLS.sub("", folded))


def same_song(
    first: tuple[str, list[str], int | None],
    second: tuple[str, list[str], int | None],
) -> bool:
    title, artists, duration = first
    other_title, other_artists, other_duration = second
    if duration is None or other_duration is None:
        return False
    if abs(duration - other_duration) > SAME_DURATION_MS:
        return False
    if normalize_title(title) != normalize_title(other_title):
        return False

    names = {normalize_artist(artist) for artist in artists} - {""}
    others = {normalize_artist(artist) for artist in other_artists} - {""}

    return bool(names & others)
