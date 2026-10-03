from enum import StrEnum


class RemovedBy(StrEnum):
    USER = "USER"
    PLATFORM = "PLATFORM"


class SyncSubjects(StrEnum):
    LIKE = "LIKE"
    PLAYLIST = "PLAYLIST"
    IMPORT = "IMPORT"


class PlaylistKinds(StrEnum):
    OWNED = "OWNED"
    FOLLOWED = "FOLLOWED"


class ImportStatuses(StrEnum):
    IDLE = "IDLE"
    SYNCING = "SYNCING"
    FAILED = "FAILED"


class SyncOutcomes(StrEnum):
    DONE = "DONE"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class SyncStatuses(StrEnum):
    PENDING = "PENDING"
    DONE = SyncOutcomes.DONE.value
    SKIPPED = SyncOutcomes.SKIPPED.value
    FAILED = SyncOutcomes.FAILED.value
