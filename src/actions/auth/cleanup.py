from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.providers import logger
from src.repositories import auth as auth_repositories


async def prune_auth(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime,
) -> dict[str, int]:
    async with session_factory() as session, session.begin():
        sessions = await auth_repositories.delete_expired_sessions(session, now=now)
        codes = await auth_repositories.delete_spent_codes(session, now=now)

    counts = {"sessions": sessions, "codes": codes}

    logger.info(
        "[Auth] Pruned",
        **counts,
    )

    return counts
