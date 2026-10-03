from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.actions.sync import enqueue_push
from src.exceptions import NotFoundError
from src.repositories import catalog as catalog_repositories
from src.repositories import library as library_repositories
from src.services import OAuthPlatform
from src.structs.enums import Platforms
from src.structs.enums import RemovedBy
from src.structs.enums import SyncSubjects
from src.structs.models.responses import LikedTrack


async def like_track(
    session: AsyncSession,
    platforms: dict[Platforms, OAuthPlatform],
    *,
    user_id: UUID,
    track_id: UUID,
    now: datetime,
) -> LikedTrack:
    if not await catalog_repositories.track_exists(session, track_id):
        raise NotFoundError("The track does not exist")

    await library_repositories.set_like(session, user_id, track_id, now=now)
    await enqueue_push(
        session,
        platforms,
        user_id=user_id,
        subject=SyncSubjects.LIKE,
        subject_id=track_id,
        now=now,
    )

    like = await library_repositories.get_like(session, user_id, track_id)
    if like is None:
        raise NotFoundError("The track does not exist")

    return like


async def unlike_track(
    session: AsyncSession,
    platforms: dict[Platforms, OAuthPlatform],
    *,
    user_id: UUID,
    track_id: UUID,
    now: datetime,
) -> None:
    if await library_repositories.get_like(session, user_id, track_id) is None:
        raise NotFoundError("The track is not liked")

    removed = await library_repositories.remove_like(
        session,
        user_id,
        track_id,
        now=now,
        removed_by=RemovedBy.USER,
    )
    if removed:
        await enqueue_push(
            session,
            platforms,
            user_id=user_id,
            subject=SyncSubjects.LIKE,
            subject_id=track_id,
            now=now,
        )
