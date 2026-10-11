from enum import StrEnum


class SessionTransports(StrEnum):
    COOKIE = "cookie"
    BEARER = "bearer"


class NameFields(StrEnum):
    NAME = "NAME"
    USERNAME = "USERNAME"


class FollowStates(StrEnum):
    NONE = "NONE"
    REQUESTED = "REQUESTED"
    FOLLOWING = "FOLLOWING"
