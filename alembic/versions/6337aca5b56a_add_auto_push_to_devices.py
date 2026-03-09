"""add auto_push to devices

Revision ID: 6337aca5b56a
Revises: fec956d2e959
Create Date: 2026-03-09 11:28:37.763449

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6337aca5b56a'
down_revision: Union[str, None] = 'fec956d2e959'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'devices',
        sa.Column('auto_push', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    )


def downgrade() -> None:
    op.drop_column('devices', 'auto_push')
