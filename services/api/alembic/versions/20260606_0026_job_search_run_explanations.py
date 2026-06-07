"""Persist job search run explanations.

Revision ID: 20260606_0026
Revises: 20260604_0025
Create Date: 2026-06-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op


revision: str = "20260606_0026"
down_revision: str | None = "20260604_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = None if context.is_offline_mode() else op.get_bind()
    existing_tables = set() if bind is None else set(sa.inspect(bind).get_table_names())
    if not context.is_offline_mode() and "job_search_runs" not in existing_tables:
        return
    existing_columns = (
        set()
        if bind is None or "job_search_runs" not in existing_tables
        else {column["name"] for column in sa.inspect(bind).get_columns("job_search_runs")}
    )
    if context.is_offline_mode() or "run_diagnostics_json" not in existing_columns:
        op.add_column(
            "job_search_runs",
            sa.Column("run_diagnostics_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        )


def downgrade() -> None:
    bind = None if context.is_offline_mode() else op.get_bind()
    existing_tables = set() if bind is None else set(sa.inspect(bind).get_table_names())
    if not context.is_offline_mode() and "job_search_runs" not in existing_tables:
        return
    existing_columns = (
        set()
        if bind is None or "job_search_runs" not in existing_tables
        else {column["name"] for column in sa.inspect(bind).get_columns("job_search_runs")}
    )
    if context.is_offline_mode() or "run_diagnostics_json" in existing_columns:
        op.drop_column("job_search_runs", "run_diagnostics_json")
