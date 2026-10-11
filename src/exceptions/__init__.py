from .custom_exceptions import AppError
from .custom_exceptions import EmailUnavailableError
from .custom_exceptions import ForbiddenError
from .custom_exceptions import InvalidCodeError
from .custom_exceptions import InvalidEmailError
from .custom_exceptions import InvalidOAuthStateError
from .custom_exceptions import NameChangeLimitedError
from .custom_exceptions import NameRequiredError
from .custom_exceptions import NoActiveDeviceError
from .custom_exceptions import NotFoundError
from .custom_exceptions import PlatformError
from .custom_exceptions import PlatformNotFoundError
from .custom_exceptions import PlatformNotLinkedError
from .custom_exceptions import PlatformPremiumRequiredError
from .custom_exceptions import PlatformRateLimitedError
from .custom_exceptions import PlatformReconnectRequiredError
from .custom_exceptions import PlatformScopesMissingError
from .custom_exceptions import PlatformTimeoutError
from .custom_exceptions import PlatformTokenRejectedError
from .custom_exceptions import PlatformUnavailableError
from .custom_exceptions import PlaybackSessionChangedError
from .custom_exceptions import QuotaExhaustedError
from .custom_exceptions import TooManyRequestsError
from .custom_exceptions import UnauthorizedError
from .custom_exceptions import UnsupportedError
from .custom_exceptions import UsernameTakenError
from .exception_handlers import register_exception_handlers


__all__ = [
    "AppError",
    "EmailUnavailableError",
    "ForbiddenError",
    "InvalidCodeError",
    "InvalidEmailError",
    "InvalidOAuthStateError",
    "NameChangeLimitedError",
    "NameRequiredError",
    "NoActiveDeviceError",
    "NotFoundError",
    "PlatformError",
    "PlatformNotFoundError",
    "PlatformNotLinkedError",
    "PlatformPremiumRequiredError",
    "PlatformRateLimitedError",
    "PlatformReconnectRequiredError",
    "PlatformScopesMissingError",
    "PlatformTimeoutError",
    "PlatformTokenRejectedError",
    "PlatformUnavailableError",
    "PlaybackSessionChangedError",
    "QuotaExhaustedError",
    "TooManyRequestsError",
    "UnauthorizedError",
    "UnsupportedError",
    "UsernameTakenError",
    "register_exception_handlers",
]
