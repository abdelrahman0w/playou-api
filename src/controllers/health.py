import asyncio
from collections.abc import Awaitable

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.providers import logger
from src.structs.enums import CheckStatuses
from src.structs.models.responses import ReadinessResponse


CHECK_TIMEOUT_SECONDS = 2.0


async def _check(
    name: str,
    probe: Awaitable[object],
) -> CheckStatuses:
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_SECONDS):
            await probe
    except Exception:
        logger.exception(
            "[Health Check] Readiness Check Failed",
            check=name,
        )

        return CheckStatuses.FAILED

    return CheckStatuses.OK


async def check_readiness(
    session: AsyncSession,
    redis: Redis,
) -> ReadinessResponse:
    database, cache = await asyncio.gather(
        _check("database", session.execute(text("select 1"))),
        _check("redis", redis.ping()),
    )
    checks = {"database": database, "redis": cache}

    return ReadinessResponse(
        status=CheckStatuses.OK
        if all(status is CheckStatuses.OK for status in checks.values())
        else CheckStatuses.FAILED,
        checks=checks,
    )
