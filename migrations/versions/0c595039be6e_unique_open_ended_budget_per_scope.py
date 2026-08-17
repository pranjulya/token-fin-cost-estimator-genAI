"""unique unbounded budget per scope

Revision ID: 0c595039be6e
Revises: 88d219d22646
Create Date: 2026-08-18 01:17:24.291907

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0c595039be6e'
down_revision: Union[str, Sequence[str], None] = '88d219d22646'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        'uq_budgets_scope_unbounded', 'budgets', ['scope_type', 'scope_id'],
        unique=True, postgresql_where=sa.text('starts_at IS NULL AND ends_at IS NULL'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        'uq_budgets_scope_unbounded', table_name='budgets',
        postgresql_where=sa.text('starts_at IS NULL AND ends_at IS NULL'),
    )
