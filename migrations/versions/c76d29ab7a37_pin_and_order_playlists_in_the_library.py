"""pin and order playlists in the library

Revision ID: c76d29ab7a37
Revises: 9db6ddbefd49
Create Date: 2026-10-12 11:12:12.561467

"""

from typing import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c76d29ab7a37"
down_revision: Union[str, Sequence[str], None] = "9db6ddbefd49"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "playlists",
        sa.Column("pinned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "playlists",
        sa.Column("library_position", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("playlists", "library_position")
    op.drop_column("playlists", "pinned_at")
