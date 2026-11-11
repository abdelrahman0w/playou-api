from asyncpg import PostgresError
from fastapi import FastAPI
from fastapi import Request
from fastapi import status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from src.exceptions.custom_exceptions import AppError
from src.exceptions.custom_exceptions import EmailUnavailableError
from src.exceptions.custom_exceptions import ForbiddenError
from src.exceptions.custom_exceptions import InvalidCodeError
from src.exceptions.custom_exceptions import InvalidEmailError
from src.exceptions.custom_exceptions import InvalidImageError
from src.exceptions.custom_exceptions import InvalidOAuthStateError
from src.exceptions.custom_exceptions import MediaUnavailableError
from src.exceptions.custom_exceptions import NameRequiredError
from src.exceptions.custom_exceptions import NoActiveDeviceError
from src.exceptions.custom_exceptions import NotFoundError
from src.exceptions.custom_exceptions import PlatformError
from src.exceptions.custom_exceptions import PlatformNotLinkedError
from src.exceptions.custom_exceptions import PlatformPremiumRequiredError
from src.exceptions.custom_exceptions import PlatformRateLimitedError
from src.exceptions.custom_exceptions import PlatformReconnectRequiredError
from src.exceptions.custom_exceptions import PlatformScopesMissingError
from src.exceptions.custom_exceptions import PlatformTimeoutError
from src.exceptions.custom_exceptions import PlatformUnavailableError
from src.exceptions.custom_exceptions import PlaybackSessionChangedError
from src.exceptions.custom_exceptions import QuotaExhaustedError
from src.exceptions.custom_exceptions import TooManyRequestsError
from src.exceptions.custom_exceptions import UnauthorizedError
from src.exceptions.custom_exceptions import UnsupportedError
from src.exceptions.custom_exceptions import UsernameTakenError
from src.providers import logger
from src.structs.enums import ErrorTypes
from src.structs.models import ErrorDetail
from src.structs.models import ErrorResponse
from src.utils import database_unreachable
from src.utils import lock_timed_out


STATUS_CODES: dict[type[AppError], int] = {
    NotFoundError: status.HTTP_404_NOT_FOUND,
    UnauthorizedError: status.HTTP_401_UNAUTHORIZED,
    ForbiddenError: status.HTTP_403_FORBIDDEN,
    InvalidCodeError: status.HTTP_400_BAD_REQUEST,
    InvalidEmailError: status.HTTP_400_BAD_REQUEST,
    InvalidOAuthStateError: status.HTTP_400_BAD_REQUEST,
    TooManyRequestsError: status.HTTP_429_TOO_MANY_REQUESTS,
    EmailUnavailableError: status.HTTP_503_SERVICE_UNAVAILABLE,
    InvalidImageError: status.HTTP_400_BAD_REQUEST,
    MediaUnavailableError: status.HTTP_503_SERVICE_UNAVAILABLE,
    UnsupportedError: status.HTTP_400_BAD_REQUEST,
    PlatformNotLinkedError: status.HTTP_409_CONFLICT,
    PlatformReconnectRequiredError: status.HTTP_409_CONFLICT,
    PlatformScopesMissingError: status.HTTP_409_CONFLICT,
    PlatformPremiumRequiredError: status.HTTP_403_FORBIDDEN,
    NoActiveDeviceError: status.HTTP_409_CONFLICT,
    PlaybackSessionChangedError: status.HTTP_409_CONFLICT,
    NameRequiredError: status.HTTP_409_CONFLICT,
    UsernameTakenError: status.HTTP_409_CONFLICT,
    PlatformTimeoutError: status.HTTP_504_GATEWAY_TIMEOUT,
    PlatformRateLimitedError: status.HTTP_503_SERVICE_UNAVAILABLE,
    PlatformUnavailableError: status.HTTP_503_SERVICE_UNAVAILABLE,
    QuotaExhaustedError: status.HTTP_503_SERVICE_UNAVAILABLE,
    PlatformError: status.HTTP_502_BAD_GATEWAY,
}


def status_code_for(exc: AppError) -> int:
    for cls in type(exc).__mro__:
        if cls in STATUS_CODES:
            return STATUS_CODES[cls]

    return status.HTTP_500_INTERNAL_SERVER_ERROR


def error_response(
    status_code: int,
    error_type: ErrorTypes,
    message: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        headers=headers,
        content=ErrorResponse(
            error=ErrorDetail(
                type=error_type,
                message=message,
            ),
        ).model_dump(mode="json"),
    )


EXPECTED_OUTAGES = (PlatformUnavailableError, QuotaExhaustedError)


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    status_code = status_code_for(exc)
    if isinstance(exc, EXPECTED_OUTAGES):
        logger.warning(
            "[Error] Platform Limited",
            error_type=exc.error_type,
            reason=exc.message,
        )
    elif status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        logger.exception(
            "[Error] Request Failure",
            exc_info=exc,
            error_type=exc.error_type,
        )

    headers = (
        {"Retry-After": str(exc.retry_after_seconds)}
        if isinstance(exc, TooManyRequestsError | PlatformRateLimitedError)
        else None
    )

    return error_response(
        status_code,
        exc.error_type,
        exc.message,
        headers,
    )


async def validation_error_handler(
    _: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    where = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
    message = str(first.get("msg", "Invalid request")).removeprefix("Value error, ")

    return error_response(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        ErrorTypes.VALIDATION,
        f"{where}: {message}" if where else message,
    )


async def database_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if database_unreachable(exc):
        logger.warning(
            "[Database] Unavailable",
            path=request.url.path,
            error=type(exc).__name__,
        )

        return error_response(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorTypes.DATABASE_UNAVAILABLE,
            "Playou is unavailable for a moment, try again",
            {"Retry-After": "5"},
        )
    if not lock_timed_out(exc):
        raise exc

    logger.warning(
        "[Database] Lock Wait Timed Out",
        path=request.url.path,
    )

    return error_response(
        status.HTTP_409_CONFLICT,
        ErrorTypes.BUSY,
        "Busy with another change, try again",
        {"Retry-After": "1"},
    )


async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "[Error] Unhandled Error",
        exc_info=exc,
    )

    return error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        ErrorTypes.INTERNAL,
        "Something went wrong on our side",
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
    for database_error in (DBAPIError, PoolTimeoutError, PostgresError, OSError):
        app.add_exception_handler(database_error, database_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
