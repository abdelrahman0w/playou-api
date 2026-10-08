"""give users a name

Revision ID: c2e75e481a3e
Revises: 5f3c1d9a8b27
Create Date: 2026-10-08 13:00:00.000000

"""

from typing import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c2e75e481a3e"
down_revision: Union[str, Sequence[str], None] = "5f3c1d9a8b27"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("users", sa.Column("name", sa.String(length=95), nullable=True))
    op.create_table(
        "name_changes",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_name_changes_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_name_changes")),
    )
    op.create_index(
        op.f("ix_name_changes_user_id_changed_at"),
        "name_changes",
        ["user_id", "changed_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_name_changes_user_id_changed_at"), table_name="name_changes")
    op.drop_table("name_changes")
    op.drop_column("users", "name")
