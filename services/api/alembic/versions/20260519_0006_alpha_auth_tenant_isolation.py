"""Add alpha auth, invites, sessions, and command logs.

Revision ID: 20260519_0006
Revises: 20260518_0005
Create Date: 2026-05-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260519_0006"
down_revision = "20260518_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "workspace_memberships",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False, server_default="owner"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "tenant_id", name="uq_workspace_memberships_user_tenant"),
    )
    op.create_index("ix_workspace_memberships_tenant", "workspace_memberships", ["tenant_id"])

    op.create_table(
        "invite_tokens",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("workspace_slug", sa.String(length=120), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_invite_tokens_email", "invite_tokens", ["email"])
    op.create_index("ix_invite_tokens_token_hash", "invite_tokens", ["token_hash"], unique=True)

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_sessions_token_hash", "user_sessions", ["token_hash"], unique=True)
    op.create_index("ix_user_sessions_user_tenant", "user_sessions", ["user_id", "tenant_id"])

    op.create_table(
        "command_interaction_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("candidate_profile_id", sa.String(length=36), sa.ForeignKey("candidate_profiles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_message", sa.Text(), nullable=False),
        sa.Column("route_selected", sa.String(length=80), nullable=True),
        sa.Column("model_provider", sa.String(length=120), nullable=True),
        sa.Column("parsed_action_payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("validation_result", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("action_applied", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("final_response", sa.Text(), nullable=False, server_default=""),
        sa.Column("error_details", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_command_interaction_logs_tenant_created", "command_interaction_logs", ["tenant_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_command_interaction_logs_tenant_created", table_name="command_interaction_logs")
    op.drop_table("command_interaction_logs")
    op.drop_index("ix_user_sessions_user_tenant", table_name="user_sessions")
    op.drop_index("ix_user_sessions_token_hash", table_name="user_sessions")
    op.drop_table("user_sessions")
    op.drop_index("ix_invite_tokens_token_hash", table_name="invite_tokens")
    op.drop_index("ix_invite_tokens_email", table_name="invite_tokens")
    op.drop_table("invite_tokens")
    op.drop_index("ix_workspace_memberships_tenant", table_name="workspace_memberships")
    op.drop_table("workspace_memberships")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
