"""Add public alpha access requests.

Revision ID: 20260520_0009
Revises: 20260519_0008
Create Date: 2026-05-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260520_0009"
down_revision = "20260519_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alpha_access_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_alpha_access_requests_email_created",
        "alpha_access_requests",
        ["email", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_alpha_access_requests_email_created", table_name="alpha_access_requests")
    op.drop_table("alpha_access_requests")
