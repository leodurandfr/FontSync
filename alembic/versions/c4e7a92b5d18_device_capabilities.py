"""device capabilities

Revision ID: c4e7a92b5d18
Revises: d81f3c2a6b94
Create Date: 2026-11-25 11:30:00.000000

Additive pure (``ADD COLUMN`` natif sous SQLite ; ``batch_alter_table`` n'est
requis que pour le ``drop_column`` du ``downgrade()``, cf. `alembic/env.py`
`render_as_batch=True`).

``devices.capabilities`` (B-32, P1-6b) : liste JSON des capacités que l'agent
annonce à chaque ``register``. Naît NULL partout : aucun agent déployé ne les
envoie encore, et rien côté serveur n'en dépend. Le downgrade la retire sans
toucher aux appareils.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4e7a92b5d18"
down_revision: Union[str, None] = "d81f3c2a6b94"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("devices", schema=None) as batch_op:
        batch_op.add_column(sa.Column("capabilities", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("devices", schema=None) as batch_op:
        batch_op.drop_column("capabilities")
