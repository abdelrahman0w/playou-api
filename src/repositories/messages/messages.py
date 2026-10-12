import math
from collections.abc import Sequence
from datetime import datetime
from typing import Any
from typing import Unpack
from uuid import UUID

from sqlalchemy import Row
from sqlalchemy import Select
from sqlalchemy import and_
from sqlalchemy import delete
from sqlalchemy import exists
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from src.repositories.catalog import get_tracks
from src.repositories.shares import shared_playlists
from src.structs import tables
from src.structs.models import Page
from src.structs.models.responses import CatalogTrack
from src.structs.models.responses import ChatMessage
from src.structs.models.responses import ConversationSummary
from src.structs.models.responses import MessagePerson
from src.structs.models.responses import MessageReaction
from src.structs.models.responses import SharedPlaylist
from src.utils.sql import any_of


def pair_of(first: UUID, second: UUID) -> str:
    return ":".join(sorted([str(first), str(second)]))


async def ensure_conversation(
    session: AsyncSession,
    first: UUID,
    second: UUID,
) -> UUID:
    conversation = tables.Conversation
    pair = pair_of(first, second)
    await session.execute(
        insert(conversation)
        .values(pair=pair)
        .on_conflict_do_nothing(index_elements=["pair"]),
    )
    conversation_id = await session.scalar(
        select(conversation.id).where(conversation.pair == pair),
    )
    if conversation_id is None:
        raise LookupError(pair)

    member = tables.ConversationMember
    await session.execute(
        insert(member)
        .values(
            [
                {"conversation_id": conversation_id, "user_id": first},
                {"conversation_id": conversation_id, "user_id": second},
            ],
        )
        .on_conflict_do_nothing(
            index_elements=["conversation_id", "user_id"],
        ),
    )

    return conversation_id


async def conversation_between(
    session: AsyncSession,
    first: UUID,
    second: UUID,
) -> UUID | None:
    conversation = tables.Conversation

    return await session.scalar(
        select(conversation.id).where(conversation.pair == pair_of(first, second)),
    )


async def message_people(
    session: AsyncSession,
    viewer_id: UUID,
    query: str,
    *,
    limit: int,
) -> list[MessagePerson]:
    user = tables.User
    conversation = tables.Conversation
    mine = aliased(tables.ConversationMember)
    theirs = aliased(tables.ConversationMember)
    follow = tables.Follow
    back = aliased(tables.Follow)
    block = tables.UserBlock
    chats = (
        select(
            conversation.id,
            conversation.last_message_at,
            theirs.user_id,
        )
        .join(
            mine,
            and_(mine.conversation_id == conversation.id, mine.user_id == viewer_id),
        )
        .join(
            theirs,
            and_(
                theirs.conversation_id == conversation.id,
                theirs.user_id != viewer_id,
            ),
        )
        .subquery()
    )
    mutual = and_(
        exists().where(
            follow.follower_id == viewer_id,
            follow.followee_id == user.id,
            follow.accepted_at.is_not(None),
        ),
        exists().where(
            back.follower_id == user.id,
            back.followee_id == viewer_id,
            back.accepted_at.is_not(None),
        ),
    )
    blocked = exists().where(
        or_(
            (block.blocker_id == viewer_id) & (block.blocked_id == user.id),
            (block.blocker_id == user.id) & (block.blocked_id == viewer_id),
        ),
    )
    statement = (
        select(user.username, user.name, chats.c.id)
        .outerjoin(chats, chats.c.user_id == user.id)
        .where(
            user.id != viewer_id,
            or_(chats.c.id.is_not(None), mutual),
            ~blocked,
        )
    )
    text = query.strip().removeprefix("@").lower()
    if text:
        statement = statement.where(
            or_(
                func.lower(user.username).contains(text, autoescape=True),
                func.lower(user.name).contains(text, autoescape=True),
            ),
        )
    rows = await session.execute(
        statement.order_by(
            chats.c.last_message_at.desc().nulls_last(),
            func.lower(user.name),
            user.id,
        ).limit(limit),
    )

    return [
        MessagePerson(username=username, name=name, chat_id=chat_id)
        for username, name, chat_id in rows
    ]


def _message(
    row: tables.Message,
    user_id: UUID,
    tracks: dict[UUID, CatalogTrack],
    playlists: dict[UUID, SharedPlaylist],
    reactions: dict[UUID, list[MessageReaction]],
) -> ChatMessage:
    unsent = row.deleted_at is not None
    track = tracks.get(row.track_id) if row.track_id and not unsent else None
    playlist = playlists.get(row.share_id) if row.share_id and not unsent else None

    return ChatMessage(
        id=row.id,
        mine=row.sender_id == user_id,
        text=None if unsent else row.text,
        track=track,
        playlist=playlist,
        unsent=unsent,
        via_link=row.via_link,
        reactions=[] if unsent else reactions.get(row.id, []),
        created_at=row.created_at,
    )


async def _messages(
    session: AsyncSession,
    rows: list[tables.Message],
    user_id: UUID,
) -> list[ChatMessage]:
    live = [row for row in rows if row.deleted_at is None]
    tracks = await get_tracks(session, {row.track_id for row in live if row.track_id})
    share_ids = {row.share_id for row in live if row.share_id}
    shares = (
        list(
            await session.scalars(
                select(tables.Share).where(
                    any_of(tables.Share.id, share_ids),
                    tables.Share.revoked_at.is_(None),
                ),
            ),
        )
        if share_ids
        else []
    )
    playlists = await shared_playlists(session, shares)
    reaction = tables.MessageReaction
    reactions: dict[UUID, list[MessageReaction]] = {}
    if live:
        for message_id, reacted_by, emoji in await session.execute(
            select(reaction.message_id, reaction.user_id, reaction.emoji)
            .where(any_of(reaction.message_id, {row.id for row in live}))
            .order_by(reaction.created_at),
        ):
            reactions.setdefault(message_id, []).append(
                MessageReaction(emoji=emoji, mine=reacted_by == user_id),
            )

    return [_message(row, user_id, tracks, playlists, reactions) for row in rows]


def _summaries_query(user_id: UUID) -> Select[Unpack[tuple[Any, ...]]]:
    mine = aliased(tables.ConversationMember)
    other = aliased(tables.ConversationMember)
    conversation = tables.Conversation
    user = tables.User

    return (
        select(
            conversation.id,
            conversation.last_message_at,
            user.name,
            user.username,
            mine.last_read_at,
            exists()
            .where(
                tables.UserBlock.blocker_id == user_id,
                tables.UserBlock.blocked_id == other.user_id,
            )
            .label("blocked_at"),
            exists()
            .where(
                tables.UserBlock.blocker_id == other.user_id,
                tables.UserBlock.blocked_id == user_id,
            )
            .label("their_block"),
        )
        .join(
            mine, and_(mine.conversation_id == conversation.id, mine.user_id == user_id)
        )
        .outerjoin(
            other,
            and_(other.conversation_id == conversation.id, other.user_id != user_id),
        )
        .outerjoin(user, user.id == other.user_id)
    )


async def _summaries(
    session: AsyncSession,
    user_id: UUID,
    rows: Sequence[Row[Unpack[tuple[Any, ...]]]],
) -> list[ConversationSummary]:
    if not rows:
        return []

    ids = [row.id for row in rows]
    message = tables.Message
    latest = list(
        await session.scalars(
            select(message)
            .where(any_of(message.conversation_id, ids))
            .ext(distinct_on(message.conversation_id))
            .order_by(message.conversation_id, message.id.desc()),
        ),
    )
    last = {
        item.conversation_id: chat
        for item, chat in zip(
            latest, await _messages(session, latest, user_id), strict=True
        )
    }

    member = tables.ConversationMember
    unread = dict(
        (
            await session.execute(
                select(message.conversation_id, func.count())
                .join(
                    member,
                    and_(
                        member.conversation_id == message.conversation_id,
                        member.user_id == user_id,
                    ),
                )
                .where(
                    any_of(message.conversation_id, ids),
                    message.sender_id != user_id,
                    message.deleted_at.is_(None),
                    member.last_read_at.is_(None)
                    | (message.created_at > member.last_read_at),
                )
                .group_by(message.conversation_id),
            )
        ).all(),
    )

    return [
        ConversationSummary(
            id=row.id,
            name=row.name,
            username=row.username,
            last_message=last.get(row.id),
            unread=unread.get(row.id, 0),
            blocked=bool(row.blocked_at),
            can_send=not row.blocked_at
            and not row.their_block
            and row.name is not None,
            last_message_at=row.last_message_at,
        )
        for row in rows
    ]


async def list_conversations(
    session: AsyncSession,
    user_id: UUID,
    *,
    with_messages: bool,
    page: int,
    page_size: int,
) -> Page[ConversationSummary]:
    conversation = tables.Conversation
    query = _summaries_query(user_id)
    if with_messages:
        query = query.where(conversation.last_message_at.is_not(None))

    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = list(
        await session.execute(
            query.order_by(
                conversation.last_message_at.desc().nulls_last(),
                conversation.created_at.desc(),
                conversation.id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size),
        ),
    )

    return Page[ConversationSummary](
        items=await _summaries(session, user_id, rows),
        page=page,
        page_size=page_size,
        total_count=total or 0,
        total_pages=math.ceil((total or 0) / page_size),
    )


async def get_summary(
    session: AsyncSession,
    conversation_id: UUID,
    user_id: UUID,
) -> ConversationSummary | None:
    rows = list(
        await session.execute(
            _summaries_query(user_id).where(tables.Conversation.id == conversation_id),
        ),
    )
    summaries = await _summaries(session, user_id, rows)

    return summaries[0] if summaries else None


async def list_messages(
    session: AsyncSession,
    conversation_id: UUID,
    user_id: UUID,
    *,
    before: UUID | None,
    limit: int,
) -> tuple[list[ChatMessage], bool]:
    message = tables.Message
    query = select(message).where(message.conversation_id == conversation_id)
    if before is not None:
        query = query.where(message.id < before)
    rows = list(
        await session.scalars(query.order_by(message.id.desc()).limit(limit + 1))
    )

    return await _messages(session, rows[:limit], user_id), len(rows) > limit


async def add_message(
    session: AsyncSession,
    conversation_id: UUID,
    sender_id: UUID,
    *,
    text: str | None,
    track_id: UUID | None,
    now: datetime,
    via_link: bool = False,
    share_id: UUID | None = None,
) -> ChatMessage:
    row = tables.Message(
        conversation_id=conversation_id,
        sender_id=sender_id,
        text=text,
        track_id=track_id,
        created_at=now,
        via_link=via_link,
        share_id=share_id,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    await session.execute(
        update(tables.Conversation)
        .where(tables.Conversation.id == conversation_id)
        .values(last_message_at=now),
    )

    (sent,) = await _messages(session, [row], sender_id)

    return sent


async def unread_in(session: AsyncSession, conversation_id: UUID, user_id: UUID) -> int:
    message = tables.Message
    member = tables.ConversationMember

    return (
        await session.scalar(
            select(func.count())
            .select_from(message)
            .join(
                member,
                and_(
                    member.conversation_id == message.conversation_id,
                    member.user_id == user_id,
                ),
            )
            .where(
                message.conversation_id == conversation_id,
                message.sender_id != user_id,
                message.deleted_at.is_(None),
                member.last_read_at.is_(None)
                | (message.created_at > member.last_read_at),
            ),
        )
        or 0
    )


async def members(session: AsyncSession, conversation_id: UUID) -> list[UUID]:
    member = tables.ConversationMember

    return list(
        await session.scalars(
            select(member.user_id).where(member.conversation_id == conversation_id),
        ),
    )


async def mark_read(
    session: AsyncSession,
    conversation_id: UUID,
    user_id: UUID,
    *,
    now: datetime,
) -> None:
    member = tables.ConversationMember
    await session.execute(
        update(member)
        .where(member.conversation_id == conversation_id, member.user_id == user_id)
        .values(last_read_at=now),
    )


async def unsend(
    session: AsyncSession,
    conversation_id: UUID,
    message_id: UUID,
    user_id: UUID,
    *,
    now: datetime,
) -> bool:
    message = tables.Message
    unsent = await session.scalar(
        update(message)
        .where(
            message.id == message_id,
            message.conversation_id == conversation_id,
            message.sender_id == user_id,
            message.deleted_at.is_(None),
        )
        .values(deleted_at=now, text=None, track_id=None)
        .returning(message.id),
    )
    if unsent is None:
        return False

    await session.execute(
        delete(tables.MessageReaction).where(
            tables.MessageReaction.message_id == message_id,
        ),
    )
    await session.execute(
        update(tables.Conversation)
        .where(tables.Conversation.id == conversation_id)
        .values(updated_at=func.now()),
    )

    return True


async def react(
    session: AsyncSession,
    conversation_id: UUID,
    message_id: UUID,
    user_id: UUID,
    *,
    emoji: str | None,
) -> tuple[UUID, bool] | None:
    message = tables.Message
    sender_id = await session.scalar(
        select(message.sender_id).where(
            message.id == message_id,
            message.conversation_id == conversation_id,
            message.deleted_at.is_(None),
        ),
    )
    if sender_id is None:
        return None

    reaction = tables.MessageReaction
    before = await session.scalar(
        select(reaction.emoji).where(
            reaction.message_id == message_id,
            reaction.user_id == user_id,
        ),
    )
    if emoji is None:
        await session.execute(
            delete(reaction).where(
                reaction.message_id == message_id,
                reaction.user_id == user_id,
            ),
        )
    else:
        statement = insert(reaction).values(
            message_id=message_id,
            user_id=user_id,
            emoji=emoji,
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["message_id", "user_id"],
                set_={"emoji": emoji, "updated_at": func.now()},
            ),
        )
    if before != emoji:
        await session.execute(
            update(tables.Conversation)
            .where(tables.Conversation.id == conversation_id)
            .values(updated_at=func.clock_timestamp()),
        )

    return sender_id, before != emoji


async def other_member(
    session: AsyncSession,
    conversation_id: UUID,
    user_id: UUID,
) -> UUID | None:
    member = tables.ConversationMember

    return await session.scalar(
        select(member.user_id).where(
            member.conversation_id == conversation_id,
            member.user_id != user_id,
        ),
    )


async def touch_conversation(session: AsyncSession, first: UUID, second: UUID) -> None:
    conversation = tables.Conversation
    await session.execute(
        update(conversation)
        .where(conversation.pair == pair_of(first, second))
        .values(updated_at=func.now()),
    )


async def report_message(
    session: AsyncSession,
    user_id: UUID,
    message_id: UUID,
) -> bool:
    message = tables.Message
    member = tables.ConversationMember
    reportable = await session.scalar(
        select(message.id)
        .join(
            member,
            and_(
                member.conversation_id == message.conversation_id,
                member.user_id == user_id,
            ),
        )
        .where(message.id == message_id, message.sender_id != user_id),
    )
    if reportable is None:
        return False

    await session.execute(
        insert(tables.MessageReport)
        .values(user_id=user_id, message_id=message_id)
        .on_conflict_do_nothing(index_elements=["user_id", "message_id"]),
    )

    return True


async def updates(session: AsyncSession, user_id: UUID) -> tuple[str, int]:
    mine = aliased(tables.ConversationMember)
    everyone = aliased(tables.ConversationMember)
    conversation = tables.Conversation
    changed = (
        await session.execute(
            select(
                func.max(conversation.updated_at),
                func.max(everyone.updated_at),
                func.count(func.distinct(conversation.id)),
            )
            .join(
                mine,
                and_(mine.conversation_id == conversation.id, mine.user_id == user_id),
            )
            .join(everyone, everyone.conversation_id == conversation.id),
        )
    ).one()

    message = tables.Message
    unread = await session.scalar(
        select(func.count())
        .select_from(message)
        .join(
            mine,
            and_(
                mine.conversation_id == message.conversation_id, mine.user_id == user_id
            ),
        )
        .where(
            message.sender_id != user_id,
            message.deleted_at.is_(None),
            ~exists().where(
                tables.UserBlock.blocker_id == user_id,
                tables.UserBlock.blocked_id == message.sender_id,
            ),
            mine.last_read_at.is_(None) | (message.created_at > mine.last_read_at),
        ),
    )
    tag = ":".join(
        str(int(value.timestamp() * 1_000_000))
        if isinstance(value, datetime)
        else str(value)
        for value in changed
    )

    return f"{tag}:{unread or 0}", unread or 0


async def message_reports(
    session: AsyncSession, *, limit: int
) -> list[dict[str, object]]:
    report = tables.MessageReport
    message = tables.Message
    user = tables.User
    rows = await session.execute(
        select(
            report.message_id,
            message.text,
            user.email,
            func.count().label("reports"),
            func.max(report.created_at).label("latest"),
        )
        .join(message, message.id == report.message_id)
        .join(user, user.id == message.sender_id)
        .group_by(report.message_id, message.text, user.email)
        .order_by(func.count().desc(), func.max(report.created_at).desc())
        .limit(limit),
    )

    return [
        {
            "message_id": str(row.message_id),
            "text": row.text,
            "sender": row.email,
            "reports": row.reports,
            "latest": row.latest.isoformat(),
        }
        for row in rows
    ]
