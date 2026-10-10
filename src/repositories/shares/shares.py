import math
from datetime import datetime
from uuid import UUID

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.catalog import get_tracks
from src.structs import tables
from src.structs.enums import ShareSubjects
from src.structs.models import Page
from src.structs.models.responses import ReceivedShare
from src.structs.models.responses import SentShare
from src.structs.models.responses import ShareOpener
from src.structs.models.responses import Sharer
from src.utils.shares import share_url
from src.utils.sql import any_of


async def create_share(
    session: AsyncSession,
    user_id: UUID,
    track_id: UUID,
    *,
    code: str,
) -> bool:
    share = tables.Share
    created = await session.scalar(
        insert(share)
        .values(
            code=code,
            user_id=user_id,
            subject=ShareSubjects.TRACK,
            track_id=track_id,
        )
        .on_conflict_do_nothing(index_elements=["code"])
        .returning(share.id),
    )

    return created is not None


async def get_live_share(session: AsyncSession, code: str) -> tables.Share | None:
    share = tables.Share

    return await session.scalar(
        select(share).where(share.code == code, share.revoked_at.is_(None)),
    )


async def sharer_name(session: AsyncSession, share_id: UUID) -> str:
    user = tables.User
    share = tables.Share
    name = await session.scalar(
        select(user.name)
        .join(share, share.user_id == user.id)
        .where(share.id == share_id),
    )

    return name or ""


async def count_anonymous_open(session: AsyncSession, share_id: UUID) -> None:
    share = tables.Share
    await session.execute(
        update(share)
        .where(share.id == share_id)
        .values(anonymous_opens=share.anonymous_opens + 1),
    )


async def record_open(
    session: AsyncSession,
    share_id: UUID,
    user_id: UUID,
    *,
    now: datetime,
) -> bool:
    opened = tables.ShareOpen
    opens = await session.scalar(
        insert(opened)
        .values(
            share_id=share_id,
            user_id=user_id,
            first_opened_at=now,
            last_opened_at=now,
        )
        .on_conflict_do_update(
            index_elements=["share_id", "user_id"],
            set_={
                "opens": opened.opens + 1,
                "last_opened_at": now,
                "updated_at": func.now(),
            },
        )
        .returning(opened.opens),
    )

    return opens == 1


async def revoke_share(
    session: AsyncSession,
    user_id: UUID,
    code: str,
    *,
    now: datetime,
) -> bool:
    share = tables.Share
    revoked = await session.scalar(
        update(share)
        .where(
            share.code == code,
            share.user_id == user_id,
            share.revoked_at.is_(None),
        )
        .values(revoked_at=now)
        .returning(share.id),
    )

    return revoked is not None


async def list_sent(
    session: AsyncSession,
    user_id: UUID,
    *,
    page: int,
    page_size: int,
) -> Page[SentShare]:
    share = tables.Share
    where = [
        share.user_id == user_id,
        share.revoked_at.is_(None),
        share.track_id.is_not(None),
    ]
    total = await session.scalar(
        select(func.count()).select_from(share).where(*where),
    )
    rows = list(
        await session.scalars(
            select(share)
            .where(*where)
            .order_by(share.created_at.desc(), share.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size),
        ),
    )
    tracks = await get_tracks(session, [row.track_id for row in rows if row.track_id])

    opened = tables.ShareOpen
    user = tables.User
    openers: dict[UUID, list[ShareOpener]] = {}
    if rows:
        for share_id, name, opens, last_opened_at in await session.execute(
            select(opened.share_id, user.name, opened.opens, opened.last_opened_at)
            .join(user, user.id == opened.user_id)
            .where(any_of(opened.share_id, [row.id for row in rows]))
            .order_by(opened.last_opened_at.desc(), opened.id.desc()),
        ):
            openers.setdefault(share_id, []).append(
                ShareOpener(
                    name=name or "",
                    opens=opens,
                    last_opened_at=last_opened_at,
                ),
            )

    return Page[SentShare](
        items=[
            SentShare(
                code=row.code,
                url=share_url(row.code),
                track=tracks[row.track_id],
                created_at=row.created_at,
                anonymous_opens=row.anonymous_opens,
                opened_by=openers.get(row.id, []),
            )
            for row in rows
            if row.track_id in tracks
        ],
        page=page,
        page_size=page_size,
        total_count=total or 0,
        total_pages=math.ceil((total or 0) / page_size),
    )


async def list_received(
    session: AsyncSession,
    user_id: UUID,
    *,
    page: int,
    page_size: int,
) -> Page[ReceivedShare]:
    share = tables.Share
    opened = tables.ShareOpen
    user = tables.User
    where = [
        opened.user_id == user_id,
        share.revoked_at.is_(None),
        share.track_id.is_not(None),
    ]
    total = await session.scalar(
        select(func.count())
        .select_from(opened)
        .join(share, share.id == opened.share_id)
        .where(*where),
    )
    rows = list(
        await session.execute(
            select(share.code, share.track_id, user.name, opened.last_opened_at)
            .select_from(opened)
            .join(share, share.id == opened.share_id)
            .join(user, user.id == share.user_id)
            .where(*where)
            .order_by(opened.last_opened_at.desc(), opened.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size),
        ),
    )
    tracks = await get_tracks(
        session,
        [track_id for _, track_id, _, _ in rows if track_id],
    )

    return Page[ReceivedShare](
        items=[
            ReceivedShare(
                code=code,
                track=tracks[track_id],
                shared_by=Sharer(name=name or ""),
                opened_at=opened_at,
            )
            for code, track_id, name, opened_at in rows
            if track_id in tracks
        ],
        page=page,
        page_size=page_size,
        total_count=total or 0,
        total_pages=math.ceil((total or 0) / page_size),
    )
