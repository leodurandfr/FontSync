"""full declaration since

Revision ID: b5d2e8f1c3a7
Revises: a6c1d9e3f402
Create Date: 2026-11-25 16:00:00.000000

Additive pure (``ADD COLUMN`` natif sous SQLite ; ``batch_alter_table`` n'est
requis que pour le ``drop_column`` du ``downgrade()``).

``devices.full_declaration_since`` (M-32, P1-6c) : depuis quand l'appareil
déclare toute sa bibliothèque à chaque delta (capacité ``full-declaration``).
Naît NULL partout : le premier delta d'un agent capable sert de ligne de base
(réconciliation sans détection), et seuls les suivants peuvent conclure qu'une
police absente a été supprimée. Le downgrade la retire sans toucher aux
appareils.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b5d2e8f1c3a7"
down_revision: Union[str, None] = "a6c1d9e3f402"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("devices", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "full_declaration_since", sa.DateTime(timezone=True), nullable=True
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("devices", schema=None) as batch_op:
        batch_op.drop_column("full_declaration_since")
