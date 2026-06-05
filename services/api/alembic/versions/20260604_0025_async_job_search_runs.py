"""Add async job search run status fields.

Revision ID: 20260604_0025
Revises: 20260602_0024
Create Date: 2026-06-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op


revision: str = "20260604_0025"
down_revision: str | None = "20260602_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = None if context.is_offline_mode() else op.get_bind()
    existing_tables = set() if bind is None else set(sa.inspect(bind).get_table_names())
    existing_columns = (
        set()
        if bind is None or "job_search_runs" not in existing_tables
        else {column["name"] for column in sa.inspect(bind).get_columns("job_search_runs")}
    )

    if context.is_offline_mode() or "job_search_runs" in existing_tables:
        if "candidate_count_after_dedupe" not in existing_columns:
            op.add_column(
                "job_search_runs",
                sa.Column("candidate_count_after_dedupe", sa.Integer(), server_default="0", nullable=False),
            )
        if "provider_error_count" not in existing_columns:
            op.add_column(
                "job_search_runs",
                sa.Column("provider_error_count", sa.Integer(), server_default="0", nullable=False),
            )
        if "started_at" not in existing_columns:
            op.add_column("job_search_runs", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = None if context.is_offline_mode() else op.get_bind()
    existing_tables = set() if bind is None else set(sa.inspect(bind).get_table_names())
    existing_columns = (
        set()
        if bind is None or "job_search_runs" not in existing_tables
        else {column["name"] for column in sa.inspect(bind).get_columns("job_search_runs")}
    )

    if context.is_offline_mode() or "job_search_runs" in existing_tables:
        if "started_at" in existing_columns:
            op.drop_column("job_search_runs", "started_at")
        if "provider_error_count" in existing_columns:
            op.drop_column("job_search_runs", "provider_error_count")
        if "candidate_count_after_dedupe" in existing_columns:
            op.drop_column("job_search_runs", "candidate_count_after_dedupe")
