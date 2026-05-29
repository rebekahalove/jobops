"""Add job provider metadata fields.

Revision ID: 20260528_0016
Revises: 20260528_0015
Create Date: 2026-05-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260528_0016"
down_revision: str | None = "20260528_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("job_postings") as batch_op:
        batch_op.add_column(sa.Column("provider_type", sa.String(length=60), nullable=True))
        batch_op.add_column(sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("provider_raw_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
        batch_op.add_column(sa.Column("company_website_url", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("company_careers_url", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("ats_provider", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("ats_board_token", sa.String(length=240), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("job_postings") as batch_op:
        batch_op.drop_column("ats_board_token")
        batch_op.drop_column("ats_provider")
        batch_op.drop_column("company_careers_url")
        batch_op.drop_column("company_website_url")
        batch_op.drop_column("provider_raw_metadata")
        batch_op.drop_column("source_updated_at")
        batch_op.drop_column("provider_type")
