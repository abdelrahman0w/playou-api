from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from src.actions.messages import MessageListener
from src.actions.playback import PlaybackListener
from src.exceptions import register_exception_handlers
from src.middlewares import LogsContextualizerMiddleware
from src.middlewares import RateLimitMiddleware
from src.providers import DatabaseConnection
from src.providers import DatabaseSessions
from src.providers import RedisConnection
from src.providers import enable_async_error_tracking
from src.providers import logger
from src.providers import setup_error_tracking
from src.providers import setup_logging
from src.routes import accounts_router
from src.routes import auth_router
from src.routes import catalog_router
from src.routes import health_router
from src.routes import library_router
from src.routes import messages_router
from src.routes import playback_router
from src.routes import shares_router
from src.services import LrclibConnection
from src.services import ResendConnection
from src.services import SpotifyConnection
from src.services import YouTubeConnection
from src.settings import settings
from src.utils import connect_singletons


setup_logging(
    level=settings.app.log_level,
    json_logs=settings.app.log_json,
)
setup_error_tracking(
    settings.error_tracking,
    settings.app,
)


SINGLETONS = (
    DatabaseConnection,
    DatabaseSessions,
    RedisConnection,
    ResendConnection,
    SpotifyConnection,
    YouTubeConnection,
    LrclibConnection,
    PlaybackListener,
    MessageListener,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    enable_async_error_tracking()

    async with connect_singletons(*SINGLETONS):
        logger.info(
            "[API Lifecycle] Started The API",
            environment=settings.app.environment,
            app_version=settings.app.version,
        )

        yield

    logger.info(
        "[API Lifecycle] Stopped The API",
        environment=settings.app.environment,
        app_version=settings.app.version,
    )


app = FastAPI(
    title="Playou API",
    description="One player and library over the user's music platforms",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

register_exception_handlers(app)

app.add_middleware(
    RateLimitMiddleware,
)
app.add_middleware(
    GZipMiddleware,
    minimum_size=1000,
    compresslevel=1,
)
app.add_middleware(
    LogsContextualizerMiddleware,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors.origins,
    allow_credentials=True,
    allow_methods=[
        "GET",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
    ],
    allow_headers=[
        "Content-Type",
        "sentry-trace",
        "baggage",
    ],
    expose_headers=[
        "ETag",
        "RateLimit-Limit",
        "RateLimit-Remaining",
        "RateLimit-Reset",
        "Retry-After",
    ],
    max_age=settings.cors.max_age_seconds,
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(accounts_router)
app.include_router(catalog_router)
app.include_router(library_router)
app.include_router(messages_router)
app.include_router(playback_router)
app.include_router(shares_router)
