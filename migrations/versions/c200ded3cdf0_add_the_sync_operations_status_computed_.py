"""add the sync operations' status, computed from when they finished

Revision ID: c200ded3cdf0
Revises: d5482252fb89
Create Date: 2026-10-03 19:17:48.195472

"""

from typing import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c200ded3cdf0"
down_revision: Union[str, Sequence[str], None] = "d5482252fb89"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PENDING_INDEX = "ix_sync_operations_user_id_platform_subject_subject_id"
PENDING_COLUMNS = ["user_id", "platform", "subject", "subject_id"]
DUE_INDEX = "ix_sync_operations_next_attempt_at"


def _indexes(where: str) -> None:
    op.drop_index(PENDING_INDEX, table_name="sync_operations")
    op.create_index(
        PENDING_INDEX,
        "sync_operations",
        PENDING_COLUMNS,
        unique=True,
        postgresql_where=sa.text(where),
    )
    op.drop_index(DUE_INDEX, table_name="sync_operations")
    op.create_index(
        DUE_INDEX,
        "sync_operations",
        ["next_attempt_at"],
        postgresql_where=sa.text(where),
    )


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "sync_operations",
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "DONE",
                "SKIPPED",
                "FAILED",
                name="syncstatuses",
                native_enum=False,
                length=32,
            ),
            sa.Computed(
                "CASE WHEN finished_at IS NULL THEN 'PENDING' ELSE outcome END",
                persisted=True,
            ),
            nullable=False,
        ),
    )
    _indexes("status = 'PENDING'")


def downgrade() -> None:
    """Downgrade schema."""
    _indexes("finished_at is null")
    op.drop_column("sync_operations", "status")
