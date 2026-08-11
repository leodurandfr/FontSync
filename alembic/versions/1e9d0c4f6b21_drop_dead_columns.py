"""suppression des colonnes mortes

Revision ID: 1e9d0c4f6b21
Revises: 9c1e4f2b7a03
Create Date: 2026-08-11 18:20:00.000000

La seule révision du chantier qui recrée des tables (`batch_alter_table` avec
`drop_column` sur SQLite ne peut pas faire autrement, cf. `alembic/env.py`
`render_as_batch=True`). Elle retire les quatre colonnes mortes recensées par
`docs/PLAN-ETATS-FONTS.md` §1 :

- ``fonts.deleted_reason`` : plus lu depuis M2 (`deletion_confirmed` porte
  seul le verrou de propagation). La double écriture qui le maintenait à jour
  en parallèle s'arrête avec cette révision.
- ``fonts.storage_path`` : zéro lecture fonctionnelle — le chemin se dérive
  du hash (`services/storage.py`), jamais stocké.
- ``devices.sync_status`` / ``devices.last_sync_at`` : écrivain unique,
  `/ws/agent/{device_id}` (`routers/ws.py`), retiré dans le même commit — plus
  aucun agent n'ouvre ce canal depuis la bascule SSE.
- ``device_fonts.activated`` : ne peut structurellement jamais quitter
  `True` (`register_device_font` n'accepte pas le paramètre) — un booléen mort
  depuis toujours.

``PRAGMA foreign_keys`` reste **désactivé** pendant l'exécution (posture par
défaut d'Alembic hors du listener applicatif de `backend/database.py`) : la
stratégie copy-and-move de `batch_alter_table` recrée `devices` puis
`device_fonts`, et l'enforcement actif ferait échouer le `DROP TABLE` de la
table parente sur ses FK anonymes. La vérification d'intégrité se fait
**après**, par `PRAGMA foreign_key_check` (cf. §5.4 du plan).

Aucune donnée n'est recalculée à l'upgrade : les quatre colonnes retirées
n'ont plus de lecteur depuis M2 (`deleted_reason`) ou n'en ont jamais eu
(`storage_path`, `sync_status`, `last_sync_at`, `activated`). Le
``downgrade()`` les reconstruit dans l'ordre inverse, avec les valeurs
observées en production (cf. plan §5.1) :

- ``storage_path`` : recalculé déterministiquement (même formule que
  `services/storage.py`) ;
- ``deleted_reason`` : reconstruit **fidèle au comportement**
  (`deletion_confirmed = 1 → 'manual'`, propageant ; `0 →
  'quarantine_pending'`, retenu), approximatif seulement sur le libellé
  d'origine (`manual` vs `quarantine` sont interchangeables pour
  `PROPAGATING_DELETION_REASONS`) ;
- ``sync_status`` / ``last_sync_at`` / ``activated`` : valeurs par défaut
  identiques à celles mesurées sur les deux appareils de prod (`'idle'`,
  `NULL`, `1`).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1e9d0c4f6b21"
down_revision: Union[str, None] = "9c1e4f2b7a03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("device_fonts", schema=None) as batch_op:
        batch_op.drop_column("activated")

    with op.batch_alter_table("devices", schema=None) as batch_op:
        batch_op.drop_column("sync_status")
        batch_op.drop_column("last_sync_at")

    with op.batch_alter_table("fonts", schema=None) as batch_op:
        batch_op.drop_column("deleted_reason")
        batch_op.drop_column("storage_path")


def downgrade() -> None:
    with op.batch_alter_table("fonts", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("storage_path", sa.String(500), nullable=False, server_default="")
        )
        batch_op.add_column(sa.Column("deleted_reason", sa.String(30), nullable=True))

    # Chemin déterministe (`services/storage.py:_build_path`) : reconstruction exacte.
    op.execute(
        "UPDATE fonts SET storage_path = "
        "substr(file_hash, 1, 2) || '/' || file_hash || '.' || file_format"
    )
    # Reconstruction du motif : fidèle au COMPORTEMENT (le verrou), approximative
    # sur le libellé — 'manual' et 'quarantine' sont interchangeables pour
    # PROPAGATING_DELETION_REASONS, ce qu'aucun code ne lit plus pour décider.
    op.execute(
        "UPDATE fonts SET deleted_reason = "
        "CASE WHEN deletion_confirmed = 1 THEN 'manual' ELSE 'quarantine_pending' END "
        "WHERE deleted_at IS NOT NULL"
    )

    with op.batch_alter_table("devices", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "sync_status", sa.String(20), nullable=False, server_default="idle"
            )
        )

    with op.batch_alter_table("device_fonts", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("activated", sa.Boolean(), nullable=False, server_default="1")
        )
