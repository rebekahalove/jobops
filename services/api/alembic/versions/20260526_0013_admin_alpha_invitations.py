"""Add admin roles and alpha invitation tracking.

Revision ID: 20260526_0013
Revises: 20260526_0012
Create Date: 2026-05-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260526_0013"
down_revision: str | None = "20260526_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("user_type", sa.String(length=40), nullable=False, server_default="user"))
        batch_op.create_check_constraint("ck_users_user_type", "user_type IN ('user', 'admin')")

    op.create_table(
        "alpha_invitations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("invited_by_user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'accepted', 'expired', 'revoked')", name="ck_alpha_invitations_status"),
    )
    op.create_index("ix_alpha_invitations_token_hash", "alpha_invitations", ["token_hash"], unique=True)
    op.create_index("ix_alpha_invitations_email_status", "alpha_invitations", ["email", "status"])

    with op.batch_alter_table("alpha_access_requests") as batch_op:
        batch_op.add_column(sa.Column("status", sa.String(length=40), nullable=False, server_default="pending"))
        batch_op.add_column(sa.Column("invited_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("invitation_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_alpha_access_requests_invitation_id",
            "alpha_invitations",
            ["invitation_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_alpha_access_requests_status_created",
        "alpha_access_requests",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_alpha_access_requests_status_created", table_name="alpha_access_requests")
    with op.batch_alter_table("alpha_access_requests") as batch_op:
        batch_op.drop_constraint("fk_alpha_access_requests_invitation_id", type_="foreignkey")
        batch_op.drop_column("invitation_id")
        batch_op.drop_column("invited_at")
        batch_op.drop_column("status")

    op.drop_index("ix_alpha_invitations_email_status", table_name="alpha_invitations")
    op.drop_index("ix_alpha_invitations_token_hash", table_name="alpha_invitations")
    op.drop_table("alpha_invitations")

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("ck_users_user_type", type_="check")
        batch_op.drop_column("user_type")
