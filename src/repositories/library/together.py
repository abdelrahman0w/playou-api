from collections.abc import Collection
from uuid import UUID

from sqlalchemy import and_
from sqlalchemy import exists
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from src.structs import tables
from src.structs.enums import TogetherReasons


async def user_ids_by_email(
    session: AsyncSession,
    emails: Collection[str],
) -> dict[str, UUID]:
    if not emails:
        return {}

    user = tables.User
    rows = await session.execute(
        select(func.lower(user.email), user.id).where(
            func.lower(user.email).in_(list(emails)),
        ),
    )

    return {email: user_id for email, user_id in rows}


async def _liked(
    session: AsyncSession,
    user_id: UUID,
    others: Collection[UUID],
) -> set[UUID]:
    mine = tables.Like
    theirs = aliased(tables.Like)

    return set(
        await session.scalars(
            select(mine.track_id).where(
                mine.user_id == user_id,
                mine.removed_at.is_(None),
                exists().where(
                    theirs.track_id == mine.track_id,
                    theirs.user_id.in_(list(others)),
                    theirs.removed_at.is_(None),
                ),
            ),
        ),
    )


async def _in_playlists(
    session: AsyncSession,
    user_id: UUID,
    others: Collection[UUID],
) -> set[UUID]:
    item = tables.PlaylistItem
    playlist = tables.Playlist
    mine = tables.PlaylistLink
    theirs = aliased(tables.PlaylistLink)
    their_playlist = aliased(tables.Playlist)

    return set(
        await session.scalars(
            select(item.track_id)
            .distinct()
            .join(playlist, playlist.id == item.playlist_id)
            .join(mine, mine.playlist_id == playlist.id)
            .where(
                playlist.user_id == user_id,
                playlist.removed_at.is_(None),
                item.removed_at.is_(None),
                exists()
                .where(
                    theirs.user_id.in_(list(others)),
                    theirs.platform == mine.platform,
                    theirs.platform_playlist_id == mine.platform_playlist_id,
                    their_playlist.id == theirs.playlist_id,
                    their_playlist.removed_at.is_(None),
                )
                .correlate(mine),
            ),
        ),
    )


async def _sent(
    session: AsyncSession,
    user_id: UUID,
    others: Collection[UUID],
) -> set[UUID]:
    share = tables.Share
    opened = tables.ShareOpen
    others = list(others)

    return set(
        await session.scalars(
            select(share.track_id)
            .distinct()
            .join(opened, opened.share_id == share.id)
            .where(
                share.track_id.is_not(None),
                share.revoked_at.is_(None),
                or_(
                    and_(share.user_id == user_id, opened.user_id.in_(others)),
                    and_(share.user_id.in_(others), opened.user_id == user_id),
                ),
            ),
        ),
    )


async def together_track_ids(
    session: AsyncSession,
    user_id: UUID,
    others: Collection[UUID],
    *,
    reasons: Collection[TogetherReasons],
) -> set[UUID]:
    found: set[UUID] = set()
    if TogetherReasons.LIKED in reasons:
        found |= await _liked(session, user_id, others)
    if TogetherReasons.PLAYLIST in reasons:
        found |= await _in_playlists(session, user_id, others)
    if TogetherReasons.SENT in reasons:
        found |= await _sent(session, user_id, others)

    return found
