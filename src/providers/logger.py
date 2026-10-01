import inspect
import json
import logging
import sys
import traceback
from contextlib import AbstractContextManager
from datetime import UTC
from typing import Any

from loguru import logger as _logger


UVICORN_LOGGERS = ("uvicorn", "uvicorn.error")

READABLE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS!UTC}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level> | {extra}"
)


class Logger:
    def debug(
        self,
        message: str,
        **extra: Any,
    ) -> None:
        self._log("DEBUG", message, extra)

    def info(
        self,
        message: str,
        **extra: Any,
    ) -> None:
        self._log("INFO", message, extra)

    def warning(
        self,
        message: str,
        **extra: Any,
    ) -> None:
        self._log("WARNING", message, extra)

    def error(
        self,
        message: str,
        **extra: Any,
    ) -> None:
        self._log("ERROR", message, extra)

    def exception(
        self,
        message: str,
        *,
        exc_info: BaseException | None = None,
        **extra: Any,
    ) -> None:
        _logger.bind(**extra).opt(depth=1, exception=exc_info or True).error(message)

    def contextualize(
        self,
        **extra: Any,
    ) -> AbstractContextManager[None]:
        return _logger.contextualize(**extra)

    def _log(
        self,
        level: str,
        message: str,
        extra: dict[str, Any],
    ) -> None:
        _logger.bind(**extra).opt(depth=2).log(level, message)


logger = Logger()


class InterceptHandler(logging.Handler):
    def emit(
        self,
        record: logging.LogRecord,
    ) -> None:
        try:
            level: str | int = _logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = inspect.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1

        _logger.opt(
            depth=depth,
            exception=record.exc_info,
        ).log(
            level,
            record.getMessage(),
        )


def _json_sink(message: Any) -> None:
    record = message.record
    entry = {
        "timestamp": record["time"].astimezone(UTC).isoformat(),
        "level": record["level"].name,
        "message": record["message"],
        "logger": record["name"],
        "function": record["function"],
        "line": record["line"],
        **record["extra"],
    }

    if record["exception"] is not None:
        entry["exception"] = "".join(
            traceback.format_exception(*record["exception"]),
        )

    sys.stdout.write(
        json.dumps(entry, default=str) + "\n",
    )


def setup_logging(
    *,
    level: str = "INFO",
    json_logs: bool = True,
) -> None:
    _logger.remove()

    if json_logs:
        _logger.add(
            _json_sink,
            level=level,
            format="{message}",
            diagnose=False,
        )
    else:
        _logger.add(
            sys.stdout,
            level=level,
            format=READABLE_FORMAT,
            diagnose=False,
        )

    logging.basicConfig(
        handlers=[InterceptHandler()],
        level=0,
        force=True,
    )

    for name in UVICORN_LOGGERS:
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True

    access = logging.getLogger("uvicorn.access")
    access.handlers = []
    access.propagate = False

    logging.getLogger("httpx").setLevel(logging.WARNING)
