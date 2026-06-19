"""Add persisted company discovery diagnostics.

Revision ID: 20260618_0035
Revises: 20260615_0034
Create Date: 2026-06-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op


revision: str = "20260618_0035"
down_revision: str | None = "20260615_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if context.is_offline_mode() or not table_exists("company_discovery_runs"):
        op.create_table(
            "company_discovery_runs",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("candidate_profile_id", sa.String(length=36), nullable=False),
            sa.Column("command_text", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("source_path", sa.String(length=120), nullable=False),
            sa.Column("router_action", sa.String(length=80), nullable=True),
            sa.Column("router_confidence", sa.String(length=40), nullable=True),
            sa.Column("target_workspace", sa.String(length=80), nullable=True),
            sa.Column("source_provider", sa.String(length=120), nullable=True),
            sa.Column("search_grounding_enabled", sa.Boolean(), nullable=True),
            sa.Column("model_provider", sa.String(length=120), nullable=True),
            sa.Column("model_name", sa.String(length=240), nullable=True),
            sa.Column("saved_company_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("linked_company_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("duplicate_company_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("skipped_company_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("zero_new_company_reason", sa.String(length=120), nullable=True),
            sa.Column("company_discovery_preflight_blocked", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("preflight_reason", sa.String(length=160), nullable=True),
            sa.Column("run_diagnostics_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["candidate_profile_id"], ["candidate_profiles.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_company_discovery_runs_profile_created", "company_discovery_runs", ["candidate_profile_id", "created_at"])

    if context.is_offline_mode() or not table_exists("company_discovery_provider_calls"):
        op.create_table(
            "company_discovery_provider_calls",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("company_discovery_run_id", sa.String(length=36), nullable=False),
            sa.Column("stage", sa.String(length=80), nullable=False),
            sa.Column("provider", sa.String(length=120), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("label", sa.String(length=240), nullable=False),
            sa.Column("request_summary_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("result_summary_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("error_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["company_discovery_run_id"], ["company_discovery_runs.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_company_discovery_provider_calls_run_created",
            "company_discovery_provider_calls",
            ["company_discovery_run_id", "created_at"],
        )


def downgrade() -> None:
    if table_exists("company_discovery_provider_calls") and table_is_empty("company_discovery_provider_calls"):
        drop_index_if_exists("ix_company_discovery_provider_calls_run_created", "company_discovery_provider_calls")
        op.drop_table("company_discovery_provider_calls")

    if table_exists("company_discovery_runs") and table_is_empty("company_discovery_runs"):
        drop_index_if_exists("ix_company_discovery_runs_profile_created", "company_discovery_runs")
        op.drop_table("company_discovery_runs")


def table_exists(table_name: str) -> bool:
    if context.is_offline_mode():
        return True
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def table_is_empty(table_name: str) -> bool:
    if context.is_offline_mode() or not table_exists(table_name):
        return True
    return op.get_bind().execute(sa.text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one() == 0


def drop_index_if_exists(index_name: str, table_name: str) -> None:
    if context.is_offline_mode() or index_name in index_names(table_name):
        op.drop_index(index_name, table_name=table_name)


def index_names(table_name: str) -> set[str]:
    if not table_exists(table_name):
        return set()
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name) if index.get("name")}
