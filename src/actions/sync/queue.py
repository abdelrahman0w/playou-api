from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories import accounts as accounts_repositories
from src.repositories import sync as sync_repositories
from src.services import OAuthPlatform
from src.structs.enums import Platforms
from src.structs.enums import SyncSubjects
from src.structs.models import StoredAccount


def _pushes(
    platform: OAuthPlatform,
    account: StoredAccount,
    subject: SyncSubjects,
) -> bool:
    capabilities = platform.capabilities
    if subject is SyncSubjects.LIKE:
        return capabilities.like and account.push_likes

    return capabilities.playlists_write and account.push_playlists


async def enqueue_push(
    session: AsyncSession,
    platforms: dict[Platforms, OAuthPlatform],
    *,
    user_id: UUID,
    subject: SyncSubjects,
    subject_id: UUID,
    now: datetime,
) -> int:
    queued = 0

    for account in await accounts_repositories.list_accounts(session, user_id):
        platform = platforms.get(account.platform)
        if platform is None or not _pushes(platform, account, subject):
            continue

        await sync_repositories.enqueue(
            session,
            user_id=user_id,
            platform=account.platform,
            subject=subject,
            subject_id=subject_id,
            now=now,
        )
        queued += 1

    return queued
