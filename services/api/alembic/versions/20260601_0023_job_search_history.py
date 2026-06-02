"""Add job search history records.

Revision ID: 20260601_0023
Revises: 20260531_0022
Create Date: 2026-06-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op


revision: str = "20260601_0023"
down_revision: str | None = "20260531_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = None if context.is_offline_mode() else op.get_bind()
    existing_tables = set() if bind is None else set(sa.inspect(bind).get_table_names())

    if context.is_offline_mode() or "job_search_runs" not in existing_tables:
        op.create_table(
            "job_search_runs",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("candidate_profile_id", sa.String(length=36), nullable=False),
            sa.Column("command_text", sa.Text(), nullable=False),
            sa.Column("search_plan_json", sa.JSON(), nullable=False),
            sa.Column("provider_names", sa.JSON(), nullable=False),
            sa.Column("search_mode", sa.String(length=60), nullable=True),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("total_provider_results", sa.Integer(), nullable=False),
            sa.Column("total_matches_reported", sa.Integer(), nullable=True),
            sa.Column("candidate_pool_count", sa.Integer(), nullable=False),
            sa.Column("model_selected_count", sa.Integer(), nullable=False),
            sa.Column("saved_count", sa.Integer(), nullable=False),
            sa.Column("updated_existing_count", sa.Integer(), nullable=False),
            sa.Column("duplicate_count", sa.Integer(), nullable=False),
            sa.Column("skipped_count", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["candidate_profile_id"], ["candidate_profiles.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_job_search_runs_profile_created", "job_search_runs", ["candidate_profile_id", "created_at"])
        op.create_index(
            "ix_job_search_runs_profile_status_created",
            "job_search_runs",
            ["candidate_profile_id", "status", "created_at"],
        )

    if context.is_offline_mode() or "job_search_query_runs" not in existing_tables:
        op.create_table(
            "job_search_query_runs",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("job_search_run_id", sa.String(length=36), nullable=False),
            sa.Column("provider_name", sa.String(length=120), nullable=False),
            sa.Column("query", sa.Text(), nullable=True),
            sa.Column("company_name", sa.String(length=240), nullable=True),
            sa.Column("location", sa.String(length=240), nullable=True),
            sa.Column("page", sa.Integer(), nullable=True),
            sa.Column("total_matches", sa.Integer(), nullable=True),
            sa.Column("raw_result_count", sa.Integer(), nullable=False),
            sa.Column("normalized_result_count", sa.Integer(), nullable=False),
            sa.Column("deduped_result_count", sa.Integer(), nullable=False),
            sa.Column("candidate_count_after_filters", sa.Integer(), nullable=False),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["job_search_run_id"], ["job_search_runs.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_job_search_query_runs_run_created", "job_search_query_runs", ["job_search_run_id", "created_at"])
        op.create_index("ix_job_search_query_runs_provider", "job_search_query_runs", ["provider_name", "created_at"])


def downgrade() -> None:
    bind = None if context.is_offline_mode() else op.get_bind()
    existing_tables = set() if bind is None else set(sa.inspect(bind).get_table_names())

    if context.is_offline_mode() or "job_search_query_runs" in existing_tables:
        op.drop_index("ix_job_search_query_runs_provider", table_name="job_search_query_runs")
        op.drop_index("ix_job_search_query_runs_run_created", table_name="job_search_query_runs")
        op.drop_table("job_search_query_runs")
    if context.is_offline_mode() or "job_search_runs" in existing_tables:
        op.drop_index("ix_job_search_runs_profile_status_created", table_name="job_search_runs")
        op.drop_index("ix_job_search_runs_profile_created", table_name="job_search_runs")
        op.drop_table("job_search_runs")
