from typing import ClassVar

from src.structs.enums import ErrorTypes


class AppError(Exception):
    error_type: ClassVar[ErrorTypes] = ErrorTypes.INTERNAL

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(AppError):
    error_type = ErrorTypes.NOT_FOUND


class UnsupportedError(AppError):
    error_type = ErrorTypes.UNSUPPORTED


class UnauthorizedError(AppError):
    error_type = ErrorTypes.UNAUTHORIZED


class ForbiddenError(AppError):
    error_type = ErrorTypes.FORBIDDEN


class InvalidCodeError(AppError):
    error_type = ErrorTypes.INVALID_CODE


class InvalidEmailError(AppError):
    error_type = ErrorTypes.INVALID_EMAIL


class EmailUnavailableError(AppError):
    error_type = ErrorTypes.EMAIL_UNAVAILABLE


class TooManyRequestsError(AppError):
    error_type = ErrorTypes.RATE_LIMITED

    def __init__(self, message: str, *, retry_after_seconds: int) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class InvalidOAuthStateError(AppError):
    error_type = ErrorTypes.INVALID_OAUTH_STATE


class PlatformError(AppError):
    error_type = ErrorTypes.PLATFORM_ERROR


class PlatformUnavailableError(PlatformError):
    error_type = ErrorTypes.PLATFORM_UNAVAILABLE


class PlatformNotFoundError(PlatformError):
    error_type = ErrorTypes.PLATFORM_ERROR


class PlatformTimeoutError(PlatformError):
    error_type = ErrorTypes.PLATFORM_TIMEOUT


class PlatformNotLinkedError(AppError):
    error_type = ErrorTypes.PLATFORM_NOT_LINKED


class PlatformReconnectRequiredError(AppError):
    error_type = ErrorTypes.PLATFORM_RECONNECT_REQUIRED
