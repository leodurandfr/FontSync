"""drop device associations to active web fonts

Revision ID: 5e2b7c9d1f40
Revises: a43134c85b44
Create Date: 2026-11-12 20:00:00.000000

Migration de données, sans changement de schéma.

Avant le correctif de `pull_font`, télécharger une police enregistrait
l'appareil comme détenteur. Une WOFF/WOFF2 tirée, que l'agent ne sait pas
installer, n'était donc jamais déclarée : cette association fantôme faisait
lire le delta suivant comme une suppression locale, et la police partait en
corbeille. On retire les associations des seules polices web **actives**. Une
WOFF réellement présente dans un dossier scanné perd aussi la sienne, mais le
delta suivant de l'appareil la recrée (`reconcile_inventory`).

Les pierres tombales (``deleted_at`` posé) ne sont jamais touchées : leurs
associations protègent la récolte (une tombe qu'un appareil vivant déclare
encore n'est pas récoltée).

``downgrade()`` : no-op. Les lignes retirées étaient fausses ; les recréer
réintroduirait le bug, et le delta suivant reconstruit le registre réel.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5e2b7c9d1f40"
down_revision: Union[str, None] = "a43134c85b44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "DELETE FROM device_fonts WHERE font_id IN ("
        "SELECT id FROM fonts WHERE deleted_at IS NULL "
        "AND lower(file_format) IN ('woff', 'woff2'))"
    )


def downgrade() -> None:
    """No-op (see module docstring)."""
