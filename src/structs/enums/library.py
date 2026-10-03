from enum import StrEnum


class RemovedBy(StrEnum):
    USER = "USER"
    PLATFORM = "PLATFORM"


class SyncSubjects(StrEnum):
    LIKE = "LIKE"
    PLAYLIST = "PLAYLIST"


class SyncStatuses(StrEnum):
    PENDING = "PENDING"
    DONE = "DONE"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
