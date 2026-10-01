from .accounts import router as accounts_router
from .auth import router as auth_router
from .catalog import router as catalog_router
from .health import router as health_router


__all__ = [
    "accounts_router",
    "auth_router",
    "catalog_router",
    "health_router",
]
