from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError


LOCK_NOT_AVAILABLE = "55P03"
UNAVAILABLE_SQLSTATES = ("08", "57P", "53300")
FILE_ERRORS = (
    FileNotFoundError,
    IsADirectoryError,
    NotADirectoryError,
    PermissionError,
)


def _sqlstate(error: Exception) -> str:
    source = (
        error.orig.__cause__ if isinstance(error, DBAPIError) and error.orig else error
    )

    return getattr(source, "sqlstate", None) or ""


def lock_timed_out(error: Exception) -> bool:
    return _sqlstate(error) == LOCK_NOT_AVAILABLE


def database_unreachable(error: Exception) -> bool:
    if isinstance(error, FILE_ERRORS):
        return False
    if isinstance(error, OSError | PoolTimeoutError):
        return True
    if isinstance(error, DBAPIError) and error.connection_invalidated:
        return True

    return _sqlstate(error).startswith(UNAVAILABLE_SQLSTATES)
