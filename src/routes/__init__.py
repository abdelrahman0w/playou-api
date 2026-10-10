from .accounts import router as accounts_router
from .auth import router as auth_router
from .catalog import router as catalog_router
from .health import router as health_router
from .library import router as library_router
from .messages import router as messages_router
from .playback import router as playback_router
from .shares import router as shares_router


__all__ = [
    "accounts_router",
    "auth_router",
    "catalog_router",
    "health_router",
    "library_router",
    "messages_router",
    "playback_router",
    "shares_router",
]
