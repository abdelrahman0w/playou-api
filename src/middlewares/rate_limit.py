from fastapi import Request
from fastapi import status
from fastapi.responses import JSONResponse
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp
from starlette.types import Message
from starlette.types import Receive
from starlette.types import Scope
from starlette.types import Send

from src.actions import auth as auth_actions
from src.actions import rate_limit as rate_limit_actions
from src.dependencies import CACHED_USER_ID
from src.dependencies import get_client_ip
from src.dependencies import get_redis
from src.dependencies import get_session_token
from src.settings import settings
from src.structs.enums import ErrorTypes
from src.structs.models import ErrorDetail
from src.structs.models import ErrorResponse
from src.utils import client_key


UNLIMITED_PREFIXES = ("/health",)


class RateLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
    ) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        limits = settings.rate_limit
        if (
            scope["type"] != "http"
            or not limits.enabled
            or scope["path"].startswith(UNLIMITED_PREFIXES)
        ):
            await self.app(scope, receive, send)

            return

        request = Request(scope)
        ip = get_client_ip(request)
        if ip is None:
            await self.app(scope, receive, send)

            return

        redis = scope["app"].dependency_overrides.get(get_redis, get_redis)()
        token = get_session_token(request)
        user_id = await auth_actions.cached_user_id(redis, token) if token else None
        if token:
            scope.setdefault("state", {})[CACHED_USER_ID] = user_id
        result = await rate_limit_actions.hit(
            redis,
            f"user:{user_id}" if user_id is not None else client_key(ip),
            limit=limits.requests,
            window_seconds=limits.window_seconds,
            timeout_seconds=limits.timeout_seconds,
        )

        quota = {
            "RateLimit-Limit": str(result.limit),
            "RateLimit-Remaining": str(result.remaining),
            "RateLimit-Reset": str(result.reset),
        }

        if not result.allowed:
            message = f"Too many requests, try again in {result.reset} seconds"
            response = JSONResponse(
                ErrorResponse(
                    error=ErrorDetail(
                        type=ErrorTypes.RATE_LIMITED,
                        message=message,
                    ),
                ).model_dump(mode="json"),
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                headers=quota | {"Retry-After": str(result.reset)},
            )
            await response(scope, receive, send)

            return

        async def send_with_quota(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).update(quota)

            await send(message)

        await self.app(scope, receive, send_with_quota)
