"""nullable tg_user_id, unique name for nameless-tg counterparties

Revision ID: 8c4e2a19b7d0
Revises: d6c1bc5e8868
Create Date: 2026-09-02 22:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8c4e2a19b7d0'
down_revision: Union[str, Sequence[str], None] = 'd6c1bc5e8868'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('counterparties', 'tg_user_id',
               existing_type=sa.Integer(),
               nullable=True)
    op.execute(
        """
        CREATE UNIQUE INDEX uq_counterparties_lower_name_null_tg
        ON counterparties (lower(name))
        WHERE tg_user_id IS NULL
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS uq_counterparties_lower_name_null_tg")
    op.alter_column('counterparties', 'tg_user_id',
               existing_type=sa.Integer(),
               nullable=False)
