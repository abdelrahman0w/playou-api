from enum import StrEnum


class Platforms(StrEnum):
    SPOTIFY = "spotify"


class AccountStatuses(StrEnum):
    ACTIVE = "ACTIVE"
    NEEDS_RECONNECT = "NEEDS_RECONNECT"


class SearchStatuses(StrEnum):
    OK = "OK"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    RATE_LIMITED = "RATE_LIMITED"
    NEEDS_RECONNECT = "NEEDS_RECONNECT"
