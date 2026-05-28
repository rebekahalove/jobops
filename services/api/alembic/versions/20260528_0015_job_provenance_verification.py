"""Add job provenance and URL verification fields.

Revision ID: 20260528_0015
Revises: 20260528_0014
Create Date: 2026-05-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260528_0015"
down_revision: str | None = "20260528_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("job_postings") as batch_op:
        batch_op.add_column(sa.Column("source_provider", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("source_result_id", sa.String(length=240), nullable=True))
        batch_op.add_column(sa.Column("source_query", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("source_url", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("provenance", sa.String(length=40), nullable=False, server_default="unknown"))
        batch_op.add_column(sa.Column("url_verification_status", sa.String(length=60), nullable=False, server_default="unverified"))
        batch_op.add_column(sa.Column("url_verification_checked_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("url_verification_summary", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("job_postings") as batch_op:
        batch_op.drop_column("url_verification_summary")
        batch_op.drop_column("url_verification_checked_at")
        batch_op.drop_column("url_verification_status")
        batch_op.drop_column("provenance")
        batch_op.drop_column("source_url")
        batch_op.drop_column("source_query")
        batch_op.drop_column("source_result_id")
        batch_op.drop_column("source_provider")
