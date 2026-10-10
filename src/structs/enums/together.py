from enum import StrEnum


class TogetherEffects(StrEnum):
    CONFETTI = "CONFETTI"
    HEARTS = "HEARTS"
    STARS = "STARS"


class TogetherReasons(StrEnum):
    LIKED = "LIKED"
    PLAYLIST = "PLAYLIST"
    SENT = "SENT"
