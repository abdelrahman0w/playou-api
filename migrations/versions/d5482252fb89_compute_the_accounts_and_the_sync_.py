"""compute the accounts and the sync operations statuses from their dates

Revision ID: d5482252fb89
Revises: 4aca9a7380fd
Create Date: 2026-10-03 19:03:16.541162

"""

from typing import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d5482252fb89"
down_revision: Union[str, Sequence[str], None] = "4aca9a7380fd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PENDING_INDEX = "ix_sync_operations_user_id_platform_subject_subject_id"
PENDING_COLUMNS = ["user_id", "platform", "subject", "subject_id"]


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "linked_accounts",
        sa.Column("reconnect_required_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "update linked_accounts set reconnect_required_at = updated_at "
        "where status = 'NEEDS_RECONNECT'",
    )
    op.drop_column("linked_accounts", "status")

    op.add_column(
        "sync_operations",
        sa.Column(
            "outcome",
            sa.Enum(
                "DONE",
                "SKIPPED",
                "FAILED",
                name="syncoutcomes",
                native_enum=False,
                length=32,
            ),
            nullable=True,
        ),
    )
    op.execute(
        "update sync_operations set outcome = status, "
        "finished_at = coalesce(finished_at, updated_at) "
        "where status != 'PENDING'",
    )
    op.execute("update sync_operations set finished_at = null where status = 'PENDING'")

    op.drop_index(PENDING_INDEX, table_name="sync_operations")
    op.create_index(
        PENDING_INDEX,
        "sync_operations",
        PENDING_COLUMNS,
        unique=True,
        postgresql_where=sa.text("finished_at is null"),
    )
    op.drop_index(
        op.f("ix_sync_operations_status_next_attempt_at"),
        table_name="sync_operations",
    )
    op.create_index(
        op.f("ix_sync_operations_next_attempt_at"),
        "sync_operations",
        ["next_attempt_at"],
        unique=False,
        postgresql_where=sa.text("finished_at is null"),
    )
    op.drop_column("sync_operations", "status")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        "sync_operations",
        sa.Column(
            "status",
            sa.VARCHAR(length=32),
            server_default="PENDING",
            nullable=False,
        ),
    )
    op.execute(
        "update sync_operations set status = outcome where outcome is not null",
    )
    op.alter_column("sync_operations", "status", server_default=None)
    op.drop_index(
        op.f("ix_sync_operations_next_attempt_at"),
        table_name="sync_operations",
        postgresql_where=sa.text("finished_at is null"),
    )
    op.create_index(
        op.f("ix_sync_operations_status_next_attempt_at"),
        "sync_operations",
        ["status", "next_attempt_at"],
        unique=False,
    )
    op.drop_index(PENDING_INDEX, table_name="sync_operations")
    op.create_index(
        PENDING_INDEX,
        "sync_operations",
        PENDING_COLUMNS,
        unique=True,
        postgresql_where=sa.text("status = 'PENDING'"),
    )
    op.drop_column("sync_operations", "outcome")

    op.add_column(
        "linked_accounts",
        sa.Column(
            "status",
            sa.VARCHAR(length=32),
            server_default="ACTIVE",
            nullable=False,
        ),
    )
    op.execute(
        "update linked_accounts set status = 'NEEDS_RECONNECT' "
        "where reconnect_required_at is not null",
    )
    op.alter_column("linked_accounts", "status", server_default=None)
    op.drop_column("linked_accounts", "reconnect_required_at")
