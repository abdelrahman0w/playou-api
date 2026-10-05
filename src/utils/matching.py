import re
import unicodedata
from functools import lru_cache

from src.structs.enums import Closeness


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
VERSION = re.compile(
    r"\b(remix|mix|live|acoustic|instrumental|cover|slowed|sped up|reverb|edit|"
    "version|karaoke|\u0631\u064a\u0645\u0643\u0633|\u0631\u064a\u0645\u064a\u0643\u0633|"
    "\u0644\u0627\u064a\u0641|\u0643\u0648\u0641\u0631)\\b",
)
VERSION_NAMES = {
    "\u0631\u064a\u0645\u0643\u0633": "remix",
    "\u0631\u064a\u0645\u064a\u0643\u0633": "remix",
    "\u0644\u0627\u064a\u0641": "live",
    "\u0643\u0648\u0641\u0631": "cover",
}
SHORTEST_SOUND = 3
CACHED_NAMES = 16_384

ARABIC = re.compile("[\u0600-\u06ff]")
HALVES = re.compile("\\s+[-\u2013\u2014/|]\\s+|\\s*/\\s*")
DIGRAPHS = (
    ("sh", "S"),
    ("ch", "S"),
    ("kh", "k"),
    ("gh", "g"),
    ("th", "t"),
    ("dh", "d"),
    ("ph", "f"),
)
SOUNDS = str.maketrans(
    {
        **dict.fromkeys("aeiouyw238", ""),
        "p": "b",
        "c": "k",
        "q": "k",
        "j": "g",
        "v": "f",
        "x": "ks",
        "5": "k",
        "7": "h",
        "9": "k",
        **dict.fromkeys(
            "\u0627\u0623\u0625\u0622\u0671\u0621\u0626\u0624\u0649\u0629\u0639\u0648\u064a",
            "",
        ),
        "\u0628": "b",
        "\u067e": "b",
        **dict.fromkeys("\u062a\u0637", "t"),
        **dict.fromkeys("\u062b\u0633\u0635", "s"),
        **dict.fromkeys("\u062c\u063a\u06af", "g"),
        **dict.fromkeys("\u062d\u0647", "h"),
        **dict.fromkeys("\u062e\u0643\u0642", "k"),
        **dict.fromkeys("\u062f\u0636", "d"),
        **dict.fromkeys("\u0630\u0632\u0638", "z"),
        "\u0631": "r",
        **dict.fromkeys("\u0634\u0686", "S"),
        **dict.fromkeys("\u0641\u06a4", "f"),
        "\u0644": "l",
        "\u0645": "m",
        "\u0646": "n",
    },
)
REPEATS = re.compile(r"(.)\1+")


@lru_cache(maxsize=CACHED_NAMES)
def _fold(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def clean_title(title: str) -> str:
    cleaned = NOISE.sub("", title)
    cleaned = SUFFIX.sub("", cleaned)

    return SPACES.sub(" ", cleaned).strip().strip("\"'\u201c\u201d\u2018\u2019").strip()


@lru_cache(maxsize=CACHED_NAMES)
def normalize_title(title: str) -> str:
    folded = FEATURING.sub("", clean_title(_fold(title)))

    return SPACES.sub(" ", SYMBOLS.sub(" ", folded)).strip()


@lru_cache(maxsize=CACHED_NAMES)
def normalize_artist(artist: str) -> str:
    folded = VEVO.sub("", TOPIC.sub("", _fold(artist).strip()))

    return SPACES.sub("", SYMBOLS.sub("", folded))


@lru_cache(maxsize=CACHED_NAMES)
def sounds(value: str) -> str:
    folded = SYMBOLS.sub("", SPACES.sub("", _fold(value)))
    folded = "".join(
        char
        for char in unicodedata.normalize("NFD", folded)
        if not unicodedata.combining(char)
    )
    for digraph, sound in DIGRAPHS:
        folded = folded.replace(digraph, sound)

    return REPEATS.sub(r"\1", folded.translate(SOUNDS))


def _halves(title: str, names: set[str]) -> set[str]:
    cleaned = FEATURING.sub("", clean_title(_fold(title)))

    return {
        cleaned,
        *(
            half
            for half in HALVES.split(cleaned)
            if (heard := sounds(VERSION.sub("", half))) and heard not in names
        ),
    }


@lru_cache(maxsize=CACHED_NAMES)
def _versions(title: str) -> frozenset[str]:
    return frozenset(
        {VERSION_NAMES.get(word, word) for word in VERSION.findall(_fold(title))}
    )


def _sound_alike(
    first: set[str],
    second: set[str],
    *,
    shortest: int = 1,
) -> bool:
    return any(
        bool(ARABIC.search(one)) != bool(ARABIC.search(other))
        and len(heard := sounds(one)) >= shortest
        and heard == sounds(other)
        for one in first
        for other in second
    )


def _same_title(
    first: tuple[str, list[str]],
    second: tuple[str, list[str]],
    *,
    across_scripts: bool,
) -> bool:
    (title, artists), (other_title, other_artists) = first, second
    if normalize_title(title) == normalize_title(other_title):
        return True

    voices = {sounds(artist) for artist in [*artists, *other_artists]}

    return across_scripts and _sound_alike(
        _halves(title, voices),
        _halves(other_title, voices),
    )


def _same_artist(
    artists: list[str],
    other_artists: list[str],
    *,
    across_scripts: bool,
) -> bool:
    names = {normalize_artist(artist) for artist in artists} - {""}
    others = {normalize_artist(artist) for artist in other_artists} - {""}
    if names & others:
        return True

    return across_scripts and _sound_alike(
        set(artists),
        set(other_artists),
        shortest=SHORTEST_SOUND,
    )


def same_song(
    first: tuple[str, list[str], int | None],
    second: tuple[str, list[str], int | None],
    *,
    across_scripts: bool = False,
) -> bool:
    title, artists, duration = first
    other_title, other_artists, other_duration = second
    if duration is None or other_duration is None:
        return False
    if abs(duration - other_duration) > SAME_DURATION_MS:
        return False
    if _versions(title) != _versions(other_title):
        return False

    return _same_title(
        (title, artists),
        (other_title, other_artists),
        across_scripts=across_scripts,
    ) and _same_artist(artists, other_artists, across_scripts=across_scripts)


def closeness(
    first: tuple[str, list[str], int | None],
    second: tuple[str, list[str], int | None],
    *,
    across_scripts: bool = False,
) -> Closeness | None:
    if same_song(first, second, across_scripts=across_scripts):
        return Closeness.SAME

    title, artists, _ = first
    other_title, other_artists, _ = second
    titled = _same_title(
        (VERSION.sub("", _fold(title)), artists),
        (VERSION.sub("", _fold(other_title)), other_artists),
        across_scripts=across_scripts,
    )
    artisted = _same_artist(artists, other_artists, across_scripts=across_scripts)
    if titled and artisted:
        if _versions(title) == _versions(other_title):
            return Closeness.LIKELY

        return Closeness.VERSION

    bare, other_bare = normalize_title(title), normalize_title(other_title)
    overlapping = min(len(bare), len(other_bare)) >= SHORTEST_SOUND and (
        bare in other_bare or other_bare in bare
    )
    if titled or (artisted and overlapping):
        return Closeness.MAYBE

    return None
