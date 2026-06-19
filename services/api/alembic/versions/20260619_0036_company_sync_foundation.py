"""Add company sync foundation.

Revision ID: 20260619_0036
Revises: 20260618_0035
Create Date: 2026-06-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op


revision: str = "20260619_0036"
down_revision: str | None = "20260618_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if context.is_offline_mode() or not table_exists("company_sources"):
        op.create_table(
            "company_sources",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("company_id", sa.String(length=36), nullable=False),
            sa.Column("source_provider", sa.String(length=120), nullable=False),
            sa.Column("provider_type", sa.String(length=60), nullable=False),
            sa.Column("provider_company_id", sa.String(length=240), nullable=True),
            sa.Column("source_result_id", sa.String(length=240), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("website_url", sa.Text(), nullable=True),
            sa.Column("linkedin_url", sa.Text(), nullable=True),
            sa.Column("careers_url", sa.Text(), nullable=True),
            sa.Column("source_query", sa.Text(), nullable=True),
            sa.Column("raw_metadata_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("ats_metadata_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("company_signals_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_company_sources_company", "company_sources", ["company_id"])
        op.create_index("ix_company_sources_provider_active", "company_sources", ["source_provider", "is_active"])
        op.create_index("ix_company_sources_provider_last_seen", "company_sources", ["source_provider", "last_seen_at"])
        op.create_index("ix_company_sources_provider_query", "company_sources", ["source_provider", "source_query"])
        op.create_index(
            "uq_company_sources_provider_company_id",
            "company_sources",
            ["source_provider", "provider_company_id"],
            unique=True,
            sqlite_where=sa.text("provider_company_id IS NOT NULL"),
            postgresql_where=sa.text("provider_company_id IS NOT NULL"),
        )
        op.create_index(
            "uq_company_sources_provider_source_url",
            "company_sources",
            ["source_provider", "source_url"],
            unique=True,
            sqlite_where=sa.text("source_url IS NOT NULL"),
            postgresql_where=sa.text("source_url IS NOT NULL"),
        )

    if context.is_offline_mode() or not table_exists("company_sync_signatures"):
        op.create_table(
            "company_sync_signatures",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("provider_name", sa.String(length=120), nullable=False),
            sa.Column("provider_type", sa.String(length=60), nullable=False),
            sa.Column("sync_kind", sa.String(length=80), nullable=False),
            sa.Column("sync_key", sa.Text(), nullable=False),
            sa.Column("query_text", sa.Text(), nullable=False),
            sa.Column("query_kind", sa.String(length=80), nullable=False),
            sa.Column("results_per_page", sa.Integer(), nullable=False, server_default="25"),
            sa.Column("max_pages", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("freshness_hours", sa.Integer(), nullable=False, server_default="168"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("verification_status", sa.String(length=40), nullable=False, server_default="verified"),
            sa.Column("source", sa.String(length=80), nullable=False, server_default="cli"),
            sa.Column("created_by", sa.String(length=200), nullable=True),
            sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_status", sa.String(length=40), nullable=True),
            sa.Column("last_raw_result_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_normalized_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_created_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_updated_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("criteria_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("sync_key", name="uq_company_sync_signatures_sync_key"),
        )
        op.create_index("ix_company_sync_signatures_provider_enabled", "company_sync_signatures", ["provider_name", "enabled"])
        op.create_index("ix_company_sync_signatures_provider_completed", "company_sync_signatures", ["provider_name", "last_completed_at"])
        op.create_index("ix_company_sync_signatures_provider_request", "company_sync_signatures", ["provider_name", "query_kind", "query_text"])
        op.create_index("ix_company_sync_signatures_status_enabled", "company_sync_signatures", ["verification_status", "enabled"])

    if context.is_offline_mode() or not table_exists("company_sync_runs"):
        op.create_table(
            "company_sync_runs",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("company_sync_signature_id", sa.String(length=36), nullable=True),
            sa.Column("sync_key", sa.Text(), nullable=False),
            sa.Column("provider_name", sa.String(length=120), nullable=False),
            sa.Column("provider_type", sa.String(length=60), nullable=False),
            sa.Column("sync_kind", sa.String(length=80), nullable=False),
            sa.Column("query_text", sa.Text(), nullable=True),
            sa.Column("query_kind", sa.String(length=80), nullable=True),
            sa.Column("criteria_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("status", sa.String(length=40), nullable=False, server_default="started"),
            sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("raw_result_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("normalized_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed_normalization_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("diagnostics_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["company_sync_signature_id"], ["company_sync_signatures.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_company_sync_runs_sync_key_completed", "company_sync_runs", ["sync_key", "completed_at"])
        op.create_index("ix_company_sync_runs_provider_completed", "company_sync_runs", ["provider_name", "completed_at"])
        op.create_index("ix_company_sync_runs_status_started", "company_sync_runs", ["status", "started_at"])
        op.create_index("ix_company_sync_runs_signature", "company_sync_runs", ["company_sync_signature_id"])
        op.create_index("ix_company_sync_runs_provider_request_completed", "company_sync_runs", ["provider_name", "query_kind", "query_text", "completed_at"])


def downgrade() -> None:
    if table_exists("company_sync_runs") and table_is_empty("company_sync_runs"):
        drop_index_if_exists("ix_company_sync_runs_provider_request_completed", "company_sync_runs")
        drop_index_if_exists("ix_company_sync_runs_signature", "company_sync_runs")
        drop_index_if_exists("ix_company_sync_runs_status_started", "company_sync_runs")
        drop_index_if_exists("ix_company_sync_runs_provider_completed", "company_sync_runs")
        drop_index_if_exists("ix_company_sync_runs_sync_key_completed", "company_sync_runs")
        op.drop_table("company_sync_runs")

    if table_exists("company_sync_signatures") and table_is_empty("company_sync_signatures"):
        drop_index_if_exists("ix_company_sync_signatures_status_enabled", "company_sync_signatures")
        drop_index_if_exists("ix_company_sync_signatures_provider_request", "company_sync_signatures")
        drop_index_if_exists("ix_company_sync_signatures_provider_completed", "company_sync_signatures")
        drop_index_if_exists("ix_company_sync_signatures_provider_enabled", "company_sync_signatures")
        op.drop_table("company_sync_signatures")

    if table_exists("company_sources") and table_is_empty("company_sources"):
        drop_index_if_exists("uq_company_sources_provider_source_url", "company_sources")
        drop_index_if_exists("uq_company_sources_provider_company_id", "company_sources")
        drop_index_if_exists("ix_company_sources_provider_query", "company_sources")
        drop_index_if_exists("ix_company_sources_provider_last_seen", "company_sources")
        drop_index_if_exists("ix_company_sources_provider_active", "company_sources")
        drop_index_if_exists("ix_company_sources_company", "company_sources")
        op.drop_table("company_sources")


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
