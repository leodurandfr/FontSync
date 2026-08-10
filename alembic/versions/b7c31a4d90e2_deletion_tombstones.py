"""suppression propagée : pierres tombales et propagation par appareil

Revision ID: b7c31a4d90e2
Revises: fbca947b83c5
Create Date: 2026-08-10 00:00:00.000000

Trois colonnes, une intention : rendre une suppression **durable**.

- ``fonts.deleted_reason`` : pourquoi la police est tombée. Sans ce motif,
  ``deleted_at`` seul ne distingue pas « supprimée » d'« absente », et la
  première machine qui détient encore le fichier la ressuscite au push suivant.
- ``fonts.purged_at`` : le fichier a quitté le stockage, la **ligne reste**.
  L'empreinte doit survivre au fichier, sinon la police revient au push suivant.
- ``devices.propagate_deletions`` : cet appareil participe-t-il à la propagation
  des suppressions ? Défaut ``False`` — rien ne s'efface sans un oui explicite.

Le backfill marque les suppressions déjà en base comme manuelles : avant cette
révision, le seul chemin vers ``deleted_at`` était le ``DELETE`` de l'interface.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7c31a4d90e2"
down_revision: Union[str, None] = "fbca947b83c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("fonts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("deleted_reason", sa.String(length=30), nullable=True))
        batch_op.add_column(
            sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True)
        )

    with op.batch_alter_table("devices", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "propagate_deletions",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            )
        )

    # Toute suppression antérieure vient de l'interface web (aucun autre chemin
    # n'écrivait `deleted_at`) : elle est intentionnelle, donc propageable.
    op.execute(
        "UPDATE fonts SET deleted_reason = 'manual' "
        "WHERE deleted_at IS NOT NULL AND deleted_reason IS NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table("devices", schema=None) as batch_op:
        batch_op.drop_column("propagate_deletions")

    with op.batch_alter_table("fonts", schema=None) as batch_op:
        batch_op.drop_column("purged_at")
        batch_op.drop_column("deleted_reason")
