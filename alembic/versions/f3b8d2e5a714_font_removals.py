"""font removals

Revision ID: f3b8d2e5a714
Revises: e4a7b2c91d35
Create Date: 2026-11-25 13:00:00.000000

Table `font_removals` : une police supprimée sur un Mac devient un retrait
**personnel** de son propriétaire (ses Mac ne la réinstallent plus, ceux qui
l'acceptent la désinstallent), au lieu d'une mise en corbeille de la
bibliothèque partagée. Ajout pur : les quarantaines existantes restent dans la
corbeille, où l'admin peut les restaurer.

``downgrade()`` : supprime la table. Les retraits personnels sont perdus : leurs
polices peuvent être réinstallées par `auto_pull`.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3b8d2e5a714"
down_revision: Union[str, None] = "e4a7b2c91d35"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "font_removals",
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("font_id", sa.Uuid(), nullable=False),
        sa.Column("source_device_id", sa.Uuid(), nullable=True),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "confirmed", sa.Boolean(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_font_removals_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["font_id"],
            ["fonts.id"],
            name="fk_font_removals_font_id_fonts",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_device_id"],
            ["devices.id"],
            name="fk_font_removals_source_device_id_devices",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_font_removals_user_id", "font_removals", ["user_id"])
    op.create_index("ix_font_removals_font_id", "font_removals", ["font_id"])


def downgrade() -> None:
    op.drop_index("ix_font_removals_font_id", table_name="font_removals")
    op.drop_index("ix_font_removals_user_id", table_name="font_removals")
    op.drop_table("font_removals")
