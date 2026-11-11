"""give people a profile picture

Revision ID: 4634c0cdea2a
Revises: 5a1c0e7d9b42
Create Date: 2026-11-11 19:00:00.000000

"""

from typing import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "4634c0cdea2a"
down_revision: Union[str, Sequence[str], None] = "5a1c0e7d9b42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users", sa.Column("avatar_key", sa.String(length=200), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "avatar_key")
