import math
from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement
from sqlalchemy import Exists
from sqlalchemy import Select
from sqlalchemy import delete
from sqlalchemy import exists
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import QueryableAttribute
from sqlalchemy.orm import aliased

from src.repositories.catalog import get_tracks
from src.structs import tables
from src.structs.enums import FollowStates
from src.structs.enums import PlaylistKinds
from src.structs.models import Page
from src.structs.models.responses import CatalogTrack
from src.structs.models.responses import Person
from src.structs.models.responses import ProfilePlaylist
from src.utils.usernames import RESERVED


async def by_username(session: AsyncSession, username: str) -> tables.User | None:
    user = tables.User

    return await session.scalar(
        select(user).where(func.lower(user.username) == username.lower()),
    )


async def username_taken(
    session: AsyncSession,
    username: str,
    *,
    except_user: UUID | None = None,
) -> bool:
    user = tables.User
    query = select(user.id).where(func.lower(user.username) == username.lower())
    if except_user is not None:
        query = query.where(user.id != except_user)

    return username in RESERVED or await session.scalar(query) is not None


def _blocked_either(
    viewer_id: UUID,
    other: ColumnElement[UUID] | QueryableAttribute[UUID] | UUID,
) -> Exists:
    block = tables.UserBlock

    return exists().where(
        or_(
            (block.blocker_id == viewer_id) & (block.blocked_id == other),
            (block.blocker_id == other) & (block.blocked_id == viewer_id),
        ),
    )


async def _states(
    session: AsyncSession,
    viewer_id: UUID,
    user_ids: list[UUID],
) -> tuple[dict[UUID, FollowStates], set[UUID]]:
    if not user_ids:
        return {}, set()

    follow = tables.Follow
    mine = await session.execute(
        select(follow.followee_id, follow.accepted_at).where(
            follow.follower_id == viewer_id,
            follow.followee_id.in_(user_ids),
        ),
    )
    states = {
        followee: FollowStates.FOLLOWING if accepted else FollowStates.REQUESTED
        for followee, accepted in mine
    }
    theirs = set(
        await session.scalars(
            select(follow.follower_id).where(
                follow.followee_id == viewer_id,
                follow.follower_id.in_(user_ids),
                follow.accepted_at.is_not(None),
            ),
        ),
    )

    return states, theirs


async def people(
    session: AsyncSession,
    viewer_id: UUID,
    users: list[tables.User],
) -> list[Person]:
    states, theirs = await _states(session, viewer_id, [user.id for user in users])

    return [
        Person(
            username=user.username,
            name=user.name,
            private=user.private,
            you_follow=states.get(user.id, FollowStates.NONE),
            follows_you=user.id in theirs,
        )
        for user in users
    ]


async def search(
    session: AsyncSession,
    viewer_id: UUID,
    query: str,
    *,
    limit: int,
) -> list[Person]:
    user = tables.User
    text = query.strip().removeprefix("@").lower()
    username = func.lower(user.username)
    name = func.lower(user.name)
    rows = list(
        await session.scalars(
            select(user)
            .where(
                user.searchable.is_(True),
                user.id != viewer_id,
                or_(
                    username.contains(text, autoescape=True),
                    name.contains(text, autoescape=True),
                ),
                ~_blocked_either(viewer_id, user.id),
            )
            .order_by(
                (username == text).desc(),
                username.startswith(text, autoescape=True).desc(),
                func.similarity(name, text).desc(),
                username,
            )
            .limit(limit),
        ),
    )

    return await people(session, viewer_id, rows)


async def blocked_either(
    session: AsyncSession, viewer_id: UUID, other_id: UUID
) -> bool:
    return bool(
        await session.scalar(select(_blocked_either(viewer_id, other_id))),
    )


async def counts(session: AsyncSession, user_id: UUID) -> tuple[int, int]:
    follow = tables.Follow
    followers = await session.scalar(
        select(func.count()).where(
            follow.followee_id == user_id,
            follow.accepted_at.is_not(None),
        ),
    )
    following = await session.scalar(
        select(func.count()).where(
            follow.follower_id == user_id,
            follow.accepted_at.is_not(None),
        ),
    )

    return followers or 0, following or 0


async def follow(
    session: AsyncSession,
    follower_id: UUID,
    followee_id: UUID,
    *,
    accepted_at: datetime | None,
) -> bool:
    follows = tables.Follow
    created = await session.scalar(
        insert(follows)
        .values(
            follower_id=follower_id,
            followee_id=followee_id,
            accepted_at=accepted_at,
        )
        .on_conflict_do_nothing(index_elements=["follower_id", "followee_id"])
        .returning(follows.follower_id),
    )

    return created is not None


async def unfollow(session: AsyncSession, follower_id: UUID, followee_id: UUID) -> bool:
    follows = tables.Follow
    removed = await session.scalar(
        delete(follows)
        .where(follows.follower_id == follower_id, follows.followee_id == followee_id)
        .returning(follows.follower_id),
    )

    return removed is not None


async def accept(
    session: AsyncSession,
    follower_id: UUID,
    followee_id: UUID,
    *,
    now: datetime,
) -> bool:
    follows = tables.Follow
    accepted = await session.scalar(
        update(follows)
        .where(
            follows.follower_id == follower_id,
            follows.followee_id == followee_id,
            follows.accepted_at.is_(None),
        )
        .values(accepted_at=now)
        .returning(follows.follower_id),
    )

    return accepted is not None


async def accept_all(
    session: AsyncSession, followee_id: UUID, *, now: datetime
) -> list[UUID]:
    follows = tables.Follow

    return list(
        await session.scalars(
            update(follows)
            .where(follows.followee_id == followee_id, follows.accepted_at.is_(None))
            .values(accepted_at=now)
            .returning(follows.follower_id),
        ),
    )


async def follows_each_other(session: AsyncSession, first: UUID, second: UUID) -> bool:
    follows = tables.Follow
    other = aliased(follows)

    return bool(
        await session.scalar(
            select(
                exists().where(
                    follows.follower_id == first,
                    follows.followee_id == second,
                    follows.accepted_at.is_not(None),
                    exists().where(
                        other.follower_id == second,
                        other.followee_id == first,
                        other.accepted_at.is_not(None),
                    ),
                ),
            ),
        ),
    )


async def is_following(
    session: AsyncSession, follower_id: UUID, followee_id: UUID
) -> bool:
    follows = tables.Follow

    return bool(
        await session.scalar(
            select(
                exists().where(
                    follows.follower_id == follower_id,
                    follows.followee_id == followee_id,
                    follows.accepted_at.is_not(None),
                ),
            ),
        ),
    )


async def _listed(
    session: AsyncSession,
    viewer_id: UUID,
    where: list[ColumnElement[bool]],
    join_on: ColumnElement[bool],
    *,
    page: int,
    page_size: int,
) -> Page[Person]:
    user = tables.User
    follows = tables.Follow
    base = (
        select(user)
        .join(follows, join_on)
        .where(*where, ~_blocked_either(viewer_id, user.id))
    )
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    rows = list(
        await session.scalars(
            base.order_by(follows.created_at.desc(), user.id)
            .offset((page - 1) * page_size)
            .limit(page_size),
        ),
    )

    return Page[Person](
        items=await people(session, viewer_id, rows),
        page=page,
        page_size=page_size,
        total_count=total or 0,
        total_pages=math.ceil((total or 0) / page_size),
    )


async def followers(
    session: AsyncSession,
    viewer_id: UUID,
    user_id: UUID,
    *,
    page: int,
    page_size: int,
) -> Page[Person]:
    follows = tables.Follow

    return await _listed(
        session,
        viewer_id,
        [follows.followee_id == user_id, follows.accepted_at.is_not(None)],
        follows.follower_id == tables.User.id,
        page=page,
        page_size=page_size,
    )


async def following(
    session: AsyncSession,
    viewer_id: UUID,
    user_id: UUID,
    *,
    page: int,
    page_size: int,
) -> Page[Person]:
    follows = tables.Follow

    return await _listed(
        session,
        viewer_id,
        [follows.follower_id == user_id, follows.accepted_at.is_not(None)],
        follows.followee_id == tables.User.id,
        page=page,
        page_size=page_size,
    )


async def requests(
    session: AsyncSession,
    user_id: UUID,
    *,
    page: int,
    page_size: int,
) -> Page[Person]:
    follows = tables.Follow

    return await _listed(
        session,
        user_id,
        [follows.followee_id == user_id, follows.accepted_at.is_(None)],
        follows.follower_id == tables.User.id,
        page=page,
        page_size=page_size,
    )


def _profile_playlists_query(user_id: UUID) -> Select[tables.Playlist, int]:
    playlist = tables.Playlist
    item = tables.PlaylistItem
    counted = (
        select(item.playlist_id, func.count().label("songs"))
        .where(item.removed_at.is_(None))
        .group_by(item.playlist_id)
        .subquery()
    )

    return (
        select(playlist, func.coalesce(counted.c.songs, 0))
        .outerjoin(counted, counted.c.playlist_id == playlist.id)
        .where(
            playlist.user_id == user_id,
            playlist.on_profile.is_(True),
            playlist.kind == PlaylistKinds.OWNED,
            playlist.removed_at.is_(None),
        )
    )


async def profile_playlists(
    session: AsyncSession, user_id: UUID
) -> list[ProfilePlaylist]:
    playlist = tables.Playlist
    rows = await session.execute(
        _profile_playlists_query(user_id).order_by(
            playlist.updated_at.desc(),
            playlist.id,
        ),
    )

    return [
        ProfilePlaylist(
            id=row.id,
            name=row.name,
            description=row.description,
            cover_url=row.cover_url,
            item_count=songs,
        )
        for row, songs in rows
    ]


async def profile_playlist(
    session: AsyncSession,
    user_id: UUID,
    playlist_id: UUID,
) -> ProfilePlaylist | None:
    found = (
        await session.execute(
            _profile_playlists_query(user_id).where(
                tables.Playlist.id == playlist_id,
            ),
        )
    ).first()
    if found is None:
        return None

    row, songs = found

    return ProfilePlaylist(
        id=row.id,
        name=row.name,
        description=row.description,
        cover_url=row.cover_url,
        item_count=songs,
    )


async def playlist_songs(
    session: AsyncSession,
    playlist_id: UUID,
    *,
    page: int,
    page_size: int,
) -> tuple[list[CatalogTrack], bool]:
    item = tables.PlaylistItem
    track_ids = list(
        await session.scalars(
            select(item.track_id)
            .where(item.playlist_id == playlist_id, item.removed_at.is_(None))
            .order_by(item.position, item.id)
            .offset((page - 1) * page_size)
            .limit(page_size + 1),
        ),
    )
    tracks = await get_tracks(session, track_ids[:page_size])

    return (
        [tracks[track_id] for track_id in track_ids[:page_size] if track_id in tracks],
        len(track_ids) > page_size,
    )


async def set_on_profile(
    session: AsyncSession,
    user_id: UUID,
    playlist_id: UUID,
    *,
    on_profile: bool,
) -> bool:
    playlist = tables.Playlist
    changed = await session.scalar(
        update(playlist)
        .where(
            playlist.id == playlist_id,
            playlist.user_id == user_id,
            playlist.kind == PlaylistKinds.OWNED,
            playlist.removed_at.is_(None),
        )
        .values(on_profile=on_profile)
        .returning(playlist.id),
    )

    return changed is not None


async def report_user(
    session: AsyncSession, reporter_id: UUID, reported_id: UUID
) -> None:
    await session.execute(
        insert(tables.UserReport)
        .values(reporter_id=reporter_id, reported_id=reported_id)
        .on_conflict_do_nothing(index_elements=["reporter_id", "reported_id"]),
    )


async def user_reports(session: AsyncSession, *, limit: int) -> list[dict[str, object]]:
    report = tables.UserReport
    user = tables.User
    rows = await session.execute(
        select(
            user.username,
            user.email,
            func.count().label("reports"),
            func.max(report.created_at).label("latest"),
        )
        .join(user, user.id == report.reported_id)
        .group_by(user.username, user.email)
        .order_by(func.count().desc(), func.max(report.created_at).desc())
        .limit(limit),
    )

    return [
        {
            "username": row.username,
            "email": row.email,
            "reports": row.reports,
            "latest": row.latest.isoformat(),
        }
        for row in rows
    ]
