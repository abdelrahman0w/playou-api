from enum import StrEnum


class LyricsStatuses(StrEnum):
    FOUND = "FOUND"
    INSTRUMENTAL = "INSTRUMENTAL"
    MISSING = "MISSING"
    HIDDEN = "HIDDEN"
    UNAVAILABLE = "UNAVAILABLE"
