"""user accounts

Revision ID: e4a7b2c91d35
Revises: d81f3c2a6b94
Create Date: 2026-11-25 12:00:00.000000

Comptes utilisateurs : tables `users`, `auth_sessions`, `invitations`, et
`devices.owner_user_id`. Ajout pur : aucune donnée existante n'est modifiée. Les
appareils déjà connus restent sans propriétaire jusqu'à la création du premier
admin, qui se les voit rattacher (`backend/services/accounts.py`). D'ici là, le
token d'instance `FONTSYNC_TOKEN` continue de fonctionner comme avant.

``downgrade()`` : supprime les trois tables et la colonne. Les comptes sont
perdus ; l'image précédente retombe sur le seul `FONTSYNC_TOKEN`.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e4a7b2c91d35"
down_revision: Union[str, None] = "d81f3c2a6b94"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=200), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    with op.batch_alter_table("devices", schema=None) as batch_op:
        batch_op.add_column(sa.Column("owner_user_id", sa.Uuid(), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_devices_owner_user_id"), ["owner_user_id"], unique=False
        )
        batch_op.create_foreign_key(
            "fk_devices_owner_user_id_users",
            "users",
            ["owner_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_table(
        "auth_sessions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        op.f("ix_auth_sessions_user_id"), "auth_sessions", ["user_id"], unique=False
    )
    op.create_table(
        "invitations",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )


def downgrade() -> None:
    op.drop_table("invitations")
    op.drop_index(op.f("ix_auth_sessions_user_id"), table_name="auth_sessions")
    op.drop_table("auth_sessions")
    with op.batch_alter_table("devices", schema=None) as batch_op:
        batch_op.drop_constraint("fk_devices_owner_user_id_users", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_devices_owner_user_id"))
        batch_op.drop_column("owner_user_id")
    op.drop_table("users")
