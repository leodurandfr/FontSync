"""booléen de confirmation de suppression

Revision ID: 9c1e4f2b7a03
Revises: 6adf18c939c6
Create Date: 2026-08-11 16:40:00.000000

Additive + backfill, aucune recréation de table (``ADD COLUMN`` est natif sous
SQLite ; le retrait de `deleted_reason`/`storage_path` reste réservé à M3).

- ``fonts.deletion_confirmed`` : LE verrou de propagation, traduction
  structurelle de la liste blanche `PROPAGATING_DELETION_REASONS`
  (`models/font.py`) — trois valeurs de `deleted_reason` écrites en six
  endroits, sans mécanisme de cohérence. Naît à ``0`` (``server_default``) : un
  ``DEFAULT '1'`` serait 1 025 ordres de désinstallation latents sur les deux
  appareils de prod, tous deux à ``propagate_deletions = 1``. Le backfill
  ci-dessous rétablit l'état réel sur les lignes déjà supprimées.
- ``fonts.harvest_candidate_since`` : mémoire du délai de grâce de la récolte
  (`docs/PLAN-ETATS-FONTS.md` §3.4, G8). Naît ``NULL`` partout — aucune police
  n'est candidate avant que L5 pose le premier passage.

À partir de cette révision, le code lit exclusivement `deletion_confirmed`
(`is_deletion_confirmed`, `deletion_confirmed_clause`,
`deletion_unconfirmed_clause`) ; les six écrivains du chemin de suppression
posent les deux colonnes en parallèle (`deleted_reason` **et**
`deletion_confirmed`) jusqu'à M3, pour rester réversibles sur le schéma comme
sur le sens tant que la seconde colonne n'a pas fait ses preuves en
production.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9c1e4f2b7a03"
down_revision: Union[str, None] = "6adf18c939c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("fonts", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "deletion_confirmed", sa.Boolean(), nullable=False, server_default="0"
            )
        )
        batch_op.add_column(
            sa.Column(
                "harvest_candidate_since", sa.DateTime(timezone=True), nullable=True
            )
        )

    # Traduction littérale de `PROPAGATING_DELETION_REASONS` (models/font.py) :
    # seuls 'manual' et 'quarantine' descendaient jusqu'aux appareils. Un motif
    # NULL ou inattendu (aucun mesuré en prod) reste NON confirmé, donc inerte —
    # forme liste blanche, jamais négation.
    op.execute(
        "UPDATE fonts SET deletion_confirmed = 1 "
        "WHERE deleted_at IS NOT NULL AND deleted_reason IN ('manual', 'quarantine')"
    )


def downgrade() -> None:
    with op.batch_alter_table("fonts", schema=None) as batch_op:
        batch_op.drop_column("harvest_candidate_since")
        batch_op.drop_column("deletion_confirmed")
