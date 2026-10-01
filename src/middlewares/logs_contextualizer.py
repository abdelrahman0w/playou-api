import time
import uuid

from fastapi import Request
from fastapi import status
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp
from starlette.types import Message
from starlette.types import Receive
from starlette.types import Scope
from starlette.types import Send

from src.dependencies import get_client_ip
from src.providers import logger


CORRELATION_ID_HEADER = "x-correlation-id"
QUIET_PATH_PREFIX = "/health"


class LogsContextualizerMiddleware:
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
        if scope["type"] != "http":
            await self.app(
                scope,
                receive,
                send,
            )

            return

        request = Request(scope)
        correlation_id = request.headers.get(CORRELATION_ID_HEADER) or str(uuid.uuid4())
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

        async def send_with_correlation_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)[CORRELATION_ID_HEADER] = correlation_id

            await send(message)

        with logger.contextualize(
            correlation_id=correlation_id,
            client_ip=get_client_ip(request) or "",
            cf_connecting_ip=request.headers.get("cf-connecting-ip", ""),
            real_ip=request.headers.get("x-real-ip", ""),
            forwarded_for=request.headers.get("x-forwarded-for", ""),
        ):
            started = time.perf_counter()

            try:
                await self.app(scope, receive, send_with_correlation_id)
            finally:
                _log_request(scope, status_code, started)


def _log_request(
    scope: Scope,
    status_code: int,
    started: float,
) -> None:
    extra = {
        "method": scope["method"],
        "path": scope["path"],
        "status_code": status_code,
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
    }

    if scope["path"].startswith(QUIET_PATH_PREFIX):
        logger.debug(
            "[API Access Request] Quiet",
            **extra,
        )
    elif status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        logger.error(
            "[API Access Request] An Error Occurred",
            **extra,
        )
    else:
        logger.info(
            "[API Access Request] Handled Successfully",
            **extra,
        )
