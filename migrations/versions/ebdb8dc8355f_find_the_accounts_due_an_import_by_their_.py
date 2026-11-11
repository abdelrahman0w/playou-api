"""find the accounts due an import by their last import

Revision ID: ebdb8dc8355f
Revises: be34b54634ac
Create Date: 2026-11-11 16:00:00.000000

"""

from typing import Sequence
from typing import Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "ebdb8dc8355f"
down_revision: Union[str, Sequence[str], None] = "be34b54634ac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        op.f("ix_linked_accounts_imported_at"),
        "linked_accounts",
        ["imported_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_linked_accounts_imported_at"), table_name="linked_accounts")
