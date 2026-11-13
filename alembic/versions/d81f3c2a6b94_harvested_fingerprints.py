"""harvested fingerprints

Revision ID: d81f3c2a6b94
Revises: 5e2b7c9d1f40
Create Date: 2026-11-13 17:00:00.000000

Table `harvested_fingerprints` (M-29) : le hash d'une police récoltée survit à
sa ligne `fonts`, pour que le delta ne la réclame plus jamais au push et que le
push agent la refuse. Ajout pur : aucune donnée existante n'est touchée.

``downgrade()`` : supprime la table. Les empreintes qu'elle contenait sont
perdues : après un retour à l'image précédente, ces polices redeviennent
« inconnues » (comportement d'avant M-29).
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d81f3c2a6b94"
down_revision: Union[str, None] = "5e2b7c9d1f40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "harvested_fingerprints",
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("harvested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_hash"),
    )


def downgrade() -> None:
    op.drop_table("harvested_fingerprints")
