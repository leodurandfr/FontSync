"""device font active state

Revision ID: a43134c85b44
Revises: 1e9d0c4f6b21
Create Date: 2026-08-12 18:12:54.366046

Additive pure (``ADD COLUMN`` natif sous SQLite ; ``batch_alter_table`` n'est
requis que pour le ``drop_column`` du ``downgrade()``, cf. `alembic/env.py`
`render_as_batch=True`).

``device_fonts.active`` : état **désiré**, distinct de l'ancienne colonne
``activated`` retirée par `1e9d0c4f6b21` (celle-ci ne pouvait structurellement
jamais quitter `True` — `register_device_font` n'en acceptait pas le
paramètre). Celle-ci est réellement écrite, par un geste explicite de
l'utilisateur (endpoints ``POST /{font_id}/activate|deactivate/{device_id}``),
jamais par `register_device_font` ni `reconcile_inventory`, qui doivent la
laisser intacte au fil des push/pull — même précaution que pour `ingestible`
(`6adf18c939c6`).

Naît à `1` partout : une police déjà associée à un appareil au moment de la
migration est considérée active, ce qui correspond à son état réel avant que
cette fonctionnalité n'existe.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a43134c85b44"
down_revision: Union[str, None] = "1e9d0c4f6b21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("device_fonts", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("active", sa.Boolean(), nullable=False, server_default="1")
        )


def downgrade() -> None:
    with op.batch_alter_table("device_fonts", schema=None) as batch_op:
        batch_op.drop_column("active")
