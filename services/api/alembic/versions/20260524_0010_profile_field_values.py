"""Add field-level profile lifecycle values.

Revision ID: 20260524_0010
Revises: 20260520_0009
Create Date: 2026-05-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260524_0010"
down_revision: str | None = "20260520_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "profile_field_values",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("candidate_profile_id", sa.String(length=36), sa.ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("field_group", sa.String(length=80), nullable=False),
        sa.Column("field_name", sa.String(length=120), nullable=False),
        sa.Column("value_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=40), nullable=False, server_default="user"),
        sa.Column("lifecycle_status", sa.String(length=40), nullable=False, server_default="generated"),
        sa.Column("visibility", sa.String(length=40), nullable=True),
        sa.Column("original_value_text", sa.Text(), nullable=True),
        sa.Column("archive_reason", sa.String(length=80), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_profile_field_values_profile_field",
        "profile_field_values",
        ["candidate_profile_id", "field_group", "field_name", "lifecycle_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_profile_field_values_profile_field", table_name="profile_field_values")
    op.drop_table("profile_field_values")
