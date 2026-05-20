"""Add password auth and account-creation invites.

Revision ID: 20260519_0008
Revises: 20260519_0007
Create Date: 2026-05-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260519_0008"
down_revision = "20260519_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("password_reset_required", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("users", sa.Column("password_expires_at", sa.DateTime(timezone=True), nullable=True))

    with op.batch_alter_table("invite_tokens") as batch_op:
        batch_op.alter_column("username", existing_type=sa.String(length=40), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("invite_tokens") as batch_op:
        batch_op.alter_column("username", existing_type=sa.String(length=40), nullable=False)

    op.drop_column("users", "password_expires_at")
    op.drop_column("users", "password_reset_required")
    op.drop_column("users", "password_hash")
