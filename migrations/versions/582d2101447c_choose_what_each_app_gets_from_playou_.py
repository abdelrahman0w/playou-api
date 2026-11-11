"""choose what each app gets from playou and the other apps

Revision ID: 582d2101447c
Revises: fbf025ef691e
Create Date: 2026-11-10 14:02:11.481203

"""

from typing import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "582d2101447c"
down_revision: Union[str, Sequence[str], None] = "fbf025ef691e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # keep in sync was the other apps' additions, and since the last fix their removals
    op.alter_column(
        "linked_accounts",
        "keep_in_sync",
        new_column_name="app_additions",
    )
    op.add_column(
        "linked_accounts",
        sa.Column(
            "playou_additions",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )
    op.add_column(
        "linked_accounts",
        sa.Column(
            "playou_removals",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )
    op.add_column(
        "linked_accounts",
        sa.Column(
            "app_removals",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.execute(
        "UPDATE linked_accounts SET app_removals = COALESCE(app_additions, false)",
    )
    op.add_column(
        "playlist_items",
        sa.Column(
            "added_from",
            sa.Enum(
                "spotify",
                "youtube",
                "soundcloud",
                name="platforms",
                native_enum=False,
                length=32,
            ),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("playlist_items", "added_from")
    op.drop_column("linked_accounts", "app_removals")
    op.drop_column("linked_accounts", "playou_removals")
    op.drop_column("linked_accounts", "playou_additions")
    op.alter_column(
        "linked_accounts",
        "app_additions",
        new_column_name="keep_in_sync",
    )
