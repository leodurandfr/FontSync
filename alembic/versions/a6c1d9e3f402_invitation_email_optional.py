"""invitation email optional

Revision ID: a6c1d9e3f402
Revises: f3b8d2e5a714
Create Date: 2026-11-25 14:10:00.000000

Une invitation n'est plus qu'un lien à partager : l'invité saisit son email en
l'ouvrant. `invitations.email` devient facultatif ; les invitations déjà créées
gardent leur adresse, que le compte reprend.

``downgrade()`` : supprime d'abord les invitations sans email (encore
inutilisées ou non, elles n'ont pas d'adresse à conserver), puis rend la
colonne obligatoire.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a6c1d9e3f402"
down_revision: Union[str, None] = "f3b8d2e5a714"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("invitations") as batch:
        batch.alter_column("email", existing_type=sa.String(320), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM invitations WHERE email IS NULL")
    with op.batch_alter_table("invitations") as batch:
        batch.alter_column("email", existing_type=sa.String(320), nullable=False)
