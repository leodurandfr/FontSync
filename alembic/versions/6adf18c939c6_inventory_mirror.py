"""inventaire miroir : device_fonts fidèle, soft delete des appareils

Revision ID: 6adf18c939c6
Revises: b7c31a4d90e2
Create Date: 2026-08-11 14:19:18.540489

Additive pure, aucune recréation de table (``ADD COLUMN``/``CREATE INDEX`` sont
natifs sous SQLite ; seul ``drop_column`` recrée, réservé au ``downgrade()``).

- ``devices.last_declaration_at`` : horodatage du dernier delta CRÉDIBLE
  (déclaration non vide, non suspecte). Sert de borne à la récolte de pierres
  tombales — ``last_seen_at`` ne peut pas jouer ce rôle, posé plus tôt par le
  register HTTP et déplacé par un simple PATCH d'UI. Naît ``NULL`` sur tout
  appareil existant : c'est ce qui tient la récolte gelée tant qu'aucune
  machine n'a re-synchronisé sous ce palier.
- ``devices.deleted_at`` : soft delete. Un appareil retiré depuis l'interface
  continue de protéger, via son registre `device_fonts` conservé, les pierres
  tombales qu'il détient encore (convention ``CLAUDE.md``, § suppression).
- ``device_fonts.ingestible`` : ce détenteur peut-il alimenter la bibliothèque
  synchronisée ? Naît à ``1`` partout — la direction sûre, un agent qui ignore
  encore ce champ bloque la récolte plutôt que de l'autoriser à tort.
- ``ix_device_fonts_font_id`` : rien ne couvre `font_id` seul aujourd'hui (la
  PK est `(device_id, font_id)`) — nécessaire aux requêtes de récolte, qui
  cherchent par police plutôt que par appareil.

Aucun backfill de données : les trois colonnes naissent dans leur valeur sûre
par construction.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6adf18c939c6"
down_revision: Union[str, None] = "b7c31a4d90e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("devices", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("last_declaration_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

    with op.batch_alter_table("device_fonts", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("ingestible", sa.Boolean(), nullable=False, server_default="1")
        )

    op.create_index(
        "ix_device_fonts_font_id", "device_fonts", ["font_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_device_fonts_font_id", table_name="device_fonts")

    with op.batch_alter_table("device_fonts", schema=None) as batch_op:
        batch_op.drop_column("ingestible")

    with op.batch_alter_table("devices", schema=None) as batch_op:
        batch_op.drop_column("deleted_at")
        batch_op.drop_column("last_declaration_at")
