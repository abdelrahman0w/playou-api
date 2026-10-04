from enum import StrEnum


class RemovedBy(StrEnum):
    USER = "USER"
    PLATFORM = "PLATFORM"
    SKIPPED = "SKIPPED"


class SyncSubjects(StrEnum):
    LIKE = "LIKE"
    PLAYLIST = "PLAYLIST"
    IMPORT = "IMPORT"


class PlaylistKinds(StrEnum):
    OWNED = "OWNED"
    FOLLOWED = "FOLLOWED"


class LikeSorts(StrEnum):
    RECENT = "RECENT"
    OLDEST = "OLDEST"
    TITLE = "TITLE"
    ARTIST = "ARTIST"


class PlaylistSorts(StrEnum):
    RECENT = "RECENT"
    NAME = "NAME"


class PlaylistImports(StrEnum):
    AUTO = "AUTO"
    ALWAYS = "ALWAYS"
    NEVER = "NEVER"


class CopyScopes(StrEnum):
    LIKES = "LIKES"
    PLAYLIST = "PLAYLIST"
    LIBRARY = "LIBRARY"


class CopyStatuses(StrEnum):
    RUNNING = "RUNNING"
    DONE = "DONE"
    CANCELED = "CANCELED"


class CopyItemStatuses(StrEnum):
    PENDING = "PENDING"
    FOUND = "FOUND"
    MISSING = "MISSING"
    DISMISSED = "DISMISSED"


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
