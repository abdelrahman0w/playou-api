from datetime import datetime
from datetime import timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.providers import logger
from src.repositories import accounts as accounts_repositories
from src.repositories import library as library_repositories
from src.services import OAuthPlatform
from src.services import reads_history
from src.settings import settings
from src.structs.enums import Platforms


PRUNE_BATCH = 5_000


async def record_listen(
    session: AsyncSession,
    platforms: dict[Platforms, OAuthPlatform],
    user_id: UUID,
    track_id: UUID,
    platform: Platforms,
    *,
    now: datetime,
) -> None:
    service = platforms.get(platform)
    account = await accounts_repositories.get_account(session, user_id, platform)
    if service is not None and account is not None:
        if reads_history(service, account.scopes):
            return

    await library_repositories.record_listen(
        session,
        user_id,
        track_id,
        platform,
        now=now,
    )


async def prune_history(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime,
) -> int:
    before = now - timedelta(days=settings.data.history_days)
    pruned = 0
    while True:
        async with session_factory() as session, session.begin():
            deleted = await library_repositories.prune_listens(
                session,
                before=before,
                limit=PRUNE_BATCH,
            )

        pruned += deleted
        if deleted < PRUNE_BATCH:
            break

    logger.info(
        "[Library] History Pruned",
        listens=pruned,
    )

    return pruned
