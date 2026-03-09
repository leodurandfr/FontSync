"""add font_families and font_family_members tables

Revision ID: fec956d2e959
Revises: 23e4bc1a6af9
Create Date: 2026-03-09 08:53:31.448295

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'fec956d2e959'
down_revision: Union[str, None] = '23e4bc1a6af9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('font_families',
        sa.Column('name', sa.String(length=500), nullable=False),
        sa.Column('slug', sa.String(length=500), nullable=False),
        sa.Column('designer', sa.String(length=500), nullable=True),
        sa.Column('manufacturer', sa.String(length=500), nullable=True),
        sa.Column('classification', sa.String(length=50), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('style_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('is_auto_grouped', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug'),
    )
    op.create_index('ix_font_families_name', 'font_families', ['name'], unique=False)
    op.create_index('ix_font_families_slug', 'font_families', ['slug'], unique=False)

    op.create_table('font_family_members',
        sa.Column('font_id', sa.UUID(), nullable=False),
        sa.Column('family_id', sa.UUID(), nullable=False),
        sa.Column('sort_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.ForeignKeyConstraint(['family_id'], ['font_families.id']),
        sa.ForeignKeyConstraint(['font_id'], ['fonts.id']),
        sa.PrimaryKeyConstraint('font_id'),
    )
    op.create_index('ix_font_family_members_family_id', 'font_family_members', ['family_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_font_family_members_family_id', table_name='font_family_members')
    op.drop_table('font_family_members')
    op.drop_index('ix_font_families_slug', table_name='font_families')
    op.drop_index('ix_font_families_name', table_name='font_families')
    op.drop_table('font_families')
