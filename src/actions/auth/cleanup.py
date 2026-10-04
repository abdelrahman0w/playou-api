from datetime import datetime
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.providers import logger
from src.repositories import auth as auth_repositories
from src.repositories import playback as playback_repositories
from src.settings import settings


async def prune_auth(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime,
) -> dict[str, int]:
    async with session_factory() as session, session.begin():
        sessions = await auth_repositories.delete_expired_sessions(session, now=now)
        codes = await auth_repositories.delete_spent_codes(session, now=now)
        playback = await playback_repositories.delete_stale_sessions(
            session,
            before=now - timedelta(days=settings.playback.session_days),
        )

    counts = {
        "sessions": sessions,
        "codes": codes,
        "playback_sessions": playback,
    }

    logger.info(
        "[Auth] Pruned",
        **counts,
    )

    return counts
