"""keep the songs people shared in their chats

Revision ID: 2a3217934103
Revises: ef8bb78c55b3
Create Date: 2026-10-11 00:08:41.116994

"""

from typing import Sequence
from typing import Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "2a3217934103"
down_revision: Union[str, Sequence[str], None] = "ef8bb78c55b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # every song someone opened from a share link, as a message from whoever shared it,
    # sent when it was first opened, and already read
    op.execute(
        """
        with opened as (
            select
                conversations.id as conversation_id,
                shares.user_id as sender_id,
                shares.track_id,
                share_opens.first_opened_at as sent_at
            from share_opens
            join shares on shares.id = share_opens.share_id
            join conversations on conversations.pair =
                least(shares.user_id::text collate "C", share_opens.user_id::text)
                || ':'
                || greatest(shares.user_id::text collate "C", share_opens.user_id::text)
            where share_opens.user_id <> shares.user_id
                and shares.track_id is not null
        )
        insert into messages (
            id, conversation_id, sender_id, track_id, created_at, updated_at
        )
        select
            uuidv7(opened.sent_at - now()),
            opened.conversation_id,
            opened.sender_id,
            opened.track_id,
            opened.sent_at,
            opened.sent_at
        from opened
        where not exists (
            select 1 from messages
            where messages.conversation_id = opened.conversation_id
                and messages.sender_id = opened.sender_id
                and messages.track_id = opened.track_id
                and messages.created_at = opened.sent_at
        )
        """,
    )
    op.execute(
        """
        with newest as (
            select conversation_id, max(created_at) as sent_at
            from messages
            where text is null and track_id is not null
            group by conversation_id
        )
        update conversations
        set last_message_at = greatest(conversations.last_message_at, newest.sent_at)
        from newest
        where newest.conversation_id = conversations.id
        """,
    )
    op.execute(
        """
        with newest as (
            select conversation_id, max(created_at) as sent_at
            from messages
            where text is null and track_id is not null
            group by conversation_id
        )
        update conversation_members
        set last_read_at = greatest(conversation_members.last_read_at, newest.sent_at)
        from newest
        where newest.conversation_id = conversation_members.conversation_id
        """,
    )


def downgrade() -> None:
    """Downgrade schema."""
    # the songs stay in the chats, they can't be told from songs sent by hand
