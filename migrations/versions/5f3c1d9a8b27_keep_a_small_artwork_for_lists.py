"""keep a small artwork for lists

Revision ID: 5f3c1d9a8b27
Revises: abccca58b07b
Create Date: 2026-10-07 18:00:00.000000

"""

from typing import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "5f3c1d9a8b27"
down_revision: Union[str, Sequence[str], None] = "abccca58b07b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("tracks", sa.Column("thumbnail_url", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("tracks", "thumbnail_url")
