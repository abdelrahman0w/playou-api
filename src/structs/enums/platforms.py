from enum import StrEnum


class Platforms(StrEnum):
    SPOTIFY = "spotify"
    YOUTUBE = "youtube"


class AccountStatuses(StrEnum):
    ACTIVE = "ACTIVE"
    NEEDS_RECONNECT = "NEEDS_RECONNECT"


class SearchStatuses(StrEnum):
    OK = "OK"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    RATE_LIMITED = "RATE_LIMITED"
    NEEDS_RECONNECT = "NEEDS_RECONNECT"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    SKIPPED = "SKIPPED"


class Closeness(StrEnum):
    SAME = "SAME"
    LIKELY = "LIKELY"
    VERSION = "VERSION"
    MAYBE = "MAYBE"
