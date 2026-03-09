"""add activated to device_fonts

Revision ID: c83de22fb795
Revises: 6337aca5b56a
Create Date: 2026-03-09 14:17:53.960083

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c83de22fb795'
down_revision: Union[str, None] = '6337aca5b56a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'device_fonts',
        sa.Column('activated', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    )


def downgrade() -> None:
    op.drop_column('device_fonts', 'activated')
