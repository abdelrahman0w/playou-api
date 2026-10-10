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
from src.structs.models import Page
from src.structs.models.responses import CatalogTrack
from src.structs.models.responses import Shared
from src.structs.models.responses import SharedPlaylist
from src.structs.models.responses import ShareLink
from src.structs.models.responses import ShareOpened
from src.structs.models.responses import Sharer
from src.utils.shares import new_code
from src.utils.shares import share_url


HOUR = 60 * 60
CODE_ATTEMPTS = 3
PLAYLIST_PAGE = 100


async def _limit(redis: Redis, user_id: UUID) -> None:
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


async def _create(
    session: AsyncSession,
    user_id: UUID,
    *,
    track_id: UUID | None = None,
    playlist_id: UUID | None = None,
) -> tuple[UUID, str]:
    for _ in range(CODE_ATTEMPTS):
        code = new_code()
        share_id = await shares_repositories.create_share(
            session,
            user_id,
            code=code,
            track_id=track_id,
            playlist_id=playlist_id,
        )
        if share_id is not None:
            return share_id, code

    raise RuntimeError("Every share code tried was taken")


async def share_playlist(
    session: AsyncSession,
    redis: Redis,
    playlist_id: UUID,
    *,
    user_id: UUID,
) -> tuple[UUID, str]:
    await _limit(redis, user_id)
    if not await shares_repositories.shareable_playlist(session, user_id, playlist_id):
        raise NotFoundError("This playlist can't be shared")

    return await _create(session, user_id, playlist_id=playlist_id)


async def share(
    session: AsyncSession,
    redis: Redis,
    *,
    track_id: UUID | None,
    playlist_id: UUID | None,
    user_id: UUID,
) -> ShareLink:
    if playlist_id is not None:
        _, code = await share_playlist(session, redis, playlist_id, user_id=user_id)

        return ShareLink(code=code, url=share_url(code))

    await _limit(redis, user_id)
    if track_id is None or not await catalog_repositories.track_exists(
        session,
        track_id,
    ):
        raise NotFoundError("The track does not exist")

    _, code = await _create(session, user_id, track_id=track_id)

    return ShareLink(code=code, url=share_url(code))


async def _live_share(
    session: AsyncSession,
    code: str,
) -> tuple[tables.Share, SharedPlaylist | None]:
    share = await shares_repositories.get_live_share(session, code)
    if share is not None and share.playlist_id is not None:
        playlist = (await shares_repositories.shared_playlists(session, [share])).get(
            share.id,
        )
        if playlist is not None:
            return share, playlist
    elif share is not None and share.track_id is not None:
        return share, None

    raise NotFoundError("This link is no longer available")


async def read_share(session: AsyncSession, code: str) -> Shared:
    share, playlist = await _live_share(session, code)
    if playlist is not None and share.playlist_id is not None:
        first = await shares_repositories.playlist_tracks(
            session,
            share.playlist_id,
            page=1,
            page_size=PLAYLIST_PAGE,
        )

        return Shared(
            code=share.code,
            created_at=share.created_at,
            playlist=playlist,
            items=first.items,
            more=(first.total_pages or 0) > 1,
        )

    track_id = share.track_id
    track = (
        (await catalog_repositories.get_tracks(session, [track_id])).get(track_id)
        if track_id
        else None
    )
    if track is None:
        raise NotFoundError("This link is no longer available")

    return Shared(code=share.code, created_at=share.created_at, track=track)


async def share_items(
    session: AsyncSession,
    code: str,
    *,
    page: int,
) -> Page[CatalogTrack]:
    share, playlist = await _live_share(session, code)
    if playlist is None or share.playlist_id is None:
        raise NotFoundError("This link is not a playlist")

    return await shares_repositories.playlist_tracks(
        session,
        share.playlist_id,
        page=page,
        page_size=PLAYLIST_PAGE,
    )


async def _into_chat(
    session: AsyncSession,
    chat: UUID,
    share: tables.Share,
    *,
    opener: UUID,
    now: datetime,
) -> None:
    caught_up = not await messages_repositories.unread_in(session, chat, opener)
    await messages_repositories.add_message(
        session,
        chat,
        share.user_id,
        text=None,
        track_id=share.track_id,
        share_id=share.id if share.playlist_id else None,
        now=now,
        via_link=True,
    )
    if caught_up:
        await messages_repositories.mark_read(session, chat, opener, now=now)


async def open_share(
    session: AsyncSession,
    code: str,
    *,
    user_id: UUID | None,
    now: datetime,
) -> ShareOpened | None:
    share, playlist = await _live_share(session, code)
    if user_id is None:
        await shares_repositories.count_anonymous_open(session, share.id)

        return None
    if user_id == share.user_id:
        return ShareOpened(track_id=share.track_id, playlist=playlist is not None)

    first = await shares_repositories.record_open(session, share.id, user_id, now=now)
    chat = await messages_repositories.ensure_conversation(
        session,
        share.user_id,
        user_id,
    )
    if first:
        await _into_chat(session, chat, share, opener=user_id, now=now)

    return ShareOpened(
        track_id=share.track_id,
        playlist=playlist is not None,
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
