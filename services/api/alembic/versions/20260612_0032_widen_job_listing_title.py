"""Widen job listing title for provider inventory.

Revision ID: 20260612_0032
Revises: 20260611_0031
Create Date: 2026-06-12 20:50:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260612_0032"
down_revision = "20260611_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("job_listings") as batch_op:
        batch_op.alter_column("title", existing_type=sa.String(length=240), type_=sa.Text(), existing_nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("job_listings") as batch_op:
        batch_op.alter_column("title", existing_type=sa.Text(), type_=sa.String(length=240), existing_nullable=False)
