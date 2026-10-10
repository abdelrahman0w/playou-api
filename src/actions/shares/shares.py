from datetime import datetime
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.actions import rate_limit as rate_limit_actions
from src.exceptions import NotFoundError
from src.exceptions import TooManyRequestsError
from src.repositories import catalog as catalog_repositories
from src.repositories import messages as messages_repositories
from src.repositories import shares as shares_repositories
from src.settings import settings
from src.structs import tables
from src.structs.models.responses import SharedTrack
from src.structs.models.responses import ShareLink
from src.structs.models.responses import ShareOpened
from src.structs.models.responses import Sharer
from src.utils.shares import new_code
from src.utils.shares import share_url


HOUR = 60 * 60
CODE_ATTEMPTS = 3


async def share_track(
    session: AsyncSession,
    redis: Redis,
    track_id: UUID,
    *,
    user_id: UUID,
) -> ShareLink:
    result = await rate_limit_actions.hit(
        redis,
        f"shares:{user_id}",
        limit=settings.shares.per_user_hour,
        window_seconds=HOUR,
    )
    if not result.allowed:
        raise TooManyRequestsError(
            "You have shared a lot, try again later",
            retry_after_seconds=result.reset,
        )
    if not await catalog_repositories.track_exists(session, track_id):
        raise NotFoundError("The track does not exist")

    for _ in range(CODE_ATTEMPTS):
        code = new_code()
        if await shares_repositories.create_share(
            session,
            user_id,
            track_id,
            code=code,
        ):
            return ShareLink(code=code, url=share_url(code))

    raise RuntimeError("Every share code tried was taken")


async def _live_track_share(
    session: AsyncSession,
    code: str,
) -> tuple[tables.Share, UUID]:
    share = await shares_repositories.get_live_share(session, code)
    if share is None or share.track_id is None:
        raise NotFoundError("This link is no longer available")

    return share, share.track_id


async def read_share(session: AsyncSession, code: str) -> SharedTrack:
    share, track_id = await _live_track_share(session, code)
    tracks = await catalog_repositories.get_tracks(session, [track_id])

    return SharedTrack(
        code=share.code,
        track=tracks[track_id],
        created_at=share.created_at,
    )


async def open_share(
    session: AsyncSession,
    code: str,
    *,
    user_id: UUID | None,
    now: datetime,
) -> ShareOpened | None:
    share, track_id = await _live_track_share(session, code)
    if user_id is None:
        await shares_repositories.count_anonymous_open(session, share.id)

        return None
    if user_id == share.user_id:
        return ShareOpened(track_id=track_id)

    await shares_repositories.record_open(session, share.id, user_id, now=now)
    await messages_repositories.ensure_conversation(session, share.user_id, user_id)

    return ShareOpened(
        track_id=track_id,
        shared_by=Sharer(name=await shares_repositories.sharer_name(session, share.id)),
    )


async def revoke_share(
    session: AsyncSession,
    code: str,
    *,
    user_id: UUID,
    now: datetime,
) -> None:
    if not await shares_repositories.revoke_share(session, user_id, code, now=now):
        raise NotFoundError("This link is no longer available")
