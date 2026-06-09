"""Add Job Sync listing, source, and run tables.

Revision ID: 20260609_0027
Revises: 20260606_0026
Create Date: 2026-06-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260609_0027"
down_revision: str | None = "20260606_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_listings",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("company_id", sa.String(length=36), sa.ForeignKey("companies.id", ondelete="SET NULL"), nullable=True),
        sa.Column("company_name", sa.String(length=240), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=True),
        sa.Column("apply_url", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("location_raw", sa.Text(), nullable=True),
        sa.Column("location_display", sa.String(length=240), nullable=True),
        sa.Column("location_city", sa.String(length=160), nullable=True),
        sa.Column("location_region", sa.String(length=160), nullable=True),
        sa.Column("location_country", sa.String(length=80), nullable=True),
        sa.Column("location_metro", sa.String(length=160), nullable=True),
        sa.Column("location_confidence", sa.String(length=40), nullable=True),
        sa.Column("remote_work_mode", sa.String(length=80), nullable=True),
        sa.Column("employment_type", sa.String(length=120), nullable=True),
        sa.Column("salary_min", sa.Integer(), nullable=True),
        sa.Column("salary_max", sa.Integer(), nullable=True),
        sa.Column("salary_currency", sa.String(length=3), nullable=True),
        sa.Column("salary_text", sa.Text(), nullable=True),
        sa.Column("description_excerpt", sa.Text(), nullable=True),
        sa.Column("full_description", sa.Text(), nullable=True),
        sa.Column("posting_date", sa.Date(), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("close_reason", sa.String(length=120), nullable=True),
        sa.Column("source_status", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_job_listings_active_last_seen", "job_listings", ["is_active", "last_seen_at"])
    op.create_index("ix_job_listings_active_source_updated", "job_listings", ["is_active", "source_updated_at"])
    op.create_index("ix_job_listings_company_active", "job_listings", ["company_id", "is_active"])
    op.create_index("ix_job_listings_company_name_active", "job_listings", ["company_name", "is_active"])
    op.create_index(
        "ix_job_listings_location_active",
        "job_listings",
        ["location_country", "location_region", "location_city", "is_active"],
    )
    op.create_index("ix_job_listings_location_metro_active", "job_listings", ["location_metro", "is_active"])
    op.create_index("ix_job_listings_remote_active", "job_listings", ["remote_work_mode", "is_active"])
    op.create_index("ix_job_listings_posting_date", "job_listings", ["posting_date"])
    op.create_index("ix_job_listings_title", "job_listings", ["title"])

    op.create_table(
        "job_listing_sources",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "job_listing_id",
            sa.String(length=36),
            sa.ForeignKey("job_listings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_provider", sa.String(length=120), nullable=False),
        sa.Column("provider_type", sa.String(length=60), nullable=False),
        sa.Column("provider_job_id", sa.String(length=240), nullable=True),
        sa.Column("source_result_id", sa.String(length=240), nullable=True),
        sa.Column("ats_provider", sa.String(length=80), nullable=True),
        sa.Column("ats_board_token", sa.String(length=240), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("apply_url", sa.Text(), nullable=True),
        sa.Column("canonical_url", sa.Text(), nullable=True),
        sa.Column("source_query", sa.Text(), nullable=True),
        sa.Column("source_location", sa.Text(), nullable=True),
        sa.Column("source_country", sa.String(length=16), nullable=True),
        sa.Column("raw_location", sa.Text(), nullable=True),
        sa.Column("raw_metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("close_reason", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_job_listing_sources_job_listing", "job_listing_sources", ["job_listing_id"])
    op.create_index("ix_job_listing_sources_provider_active", "job_listing_sources", ["source_provider", "is_active"])
    op.create_index(
        "ix_job_listing_sources_ats_board_active",
        "job_listing_sources",
        ["ats_provider", "ats_board_token", "is_active"],
    )
    op.create_index(
        "ix_job_listing_sources_provider_last_seen",
        "job_listing_sources",
        ["source_provider", "last_seen_at"],
    )
    op.create_index("ix_job_listing_sources_provider_query", "job_listing_sources", ["source_provider", "source_query"])
    op.create_index(
        "uq_job_listing_sources_greenhouse_identity",
        "job_listing_sources",
        ["source_provider", "ats_board_token", "provider_job_id"],
        unique=True,
        sqlite_where=sa.text(
            "source_provider = 'greenhouse' AND ats_board_token IS NOT NULL AND provider_job_id IS NOT NULL"
        ),
        postgresql_where=sa.text(
            "source_provider = 'greenhouse' AND ats_board_token IS NOT NULL AND provider_job_id IS NOT NULL"
        ),
    )
    op.create_index(
        "uq_job_listing_sources_provider_job_id",
        "job_listing_sources",
        ["source_provider", "provider_job_id"],
        unique=True,
        sqlite_where=sa.text("provider_job_id IS NOT NULL AND source_provider <> 'greenhouse'"),
        postgresql_where=sa.text("provider_job_id IS NOT NULL AND source_provider <> 'greenhouse'"),
    )
    op.create_table(
        "job_sync_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("sync_key", sa.Text(), nullable=False),
        sa.Column("provider_name", sa.String(length=120), nullable=False),
        sa.Column("provider_type", sa.String(length=60), nullable=False),
        sa.Column("sync_kind", sa.String(length=80), nullable=False),
        sa.Column("company_id", sa.String(length=36), sa.ForeignKey("companies.id", ondelete="SET NULL"), nullable=True),
        sa.Column("company_name", sa.String(length=240), nullable=True),
        sa.Column("ats_provider", sa.String(length=80), nullable=True),
        sa.Column("ats_board_token", sa.String(length=240), nullable=True),
        sa.Column("provider_country", sa.String(length=16), nullable=True),
        sa.Column("target_country", sa.String(length=80), nullable=True),
        sa.Column("target_location_kind", sa.String(length=80), nullable=True),
        sa.Column("display_location", sa.Text(), nullable=True),
        sa.Column("provider_where", sa.Text(), nullable=True),
        sa.Column("query_text", sa.Text(), nullable=True),
        sa.Column("query_kind", sa.String(length=80), nullable=True),
        sa.Column("criteria_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="started"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("normalized_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("closed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_normalization_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_job_sync_runs_sync_key_completed", "job_sync_runs", ["sync_key", "completed_at"])
    op.create_index("ix_job_sync_runs_provider_completed", "job_sync_runs", ["provider_name", "completed_at"])
    op.create_index("ix_job_sync_runs_status_started", "job_sync_runs", ["status", "started_at"])
    op.create_index(
        "ix_job_sync_runs_ats_board_completed",
        "job_sync_runs",
        ["ats_provider", "ats_board_token", "completed_at"],
    )
    op.create_index(
        "ix_job_sync_runs_provider_request_completed",
        "job_sync_runs",
        ["provider_name", "provider_country", "provider_where", "query_text", "completed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_job_sync_runs_provider_request_completed", table_name="job_sync_runs")
    op.drop_index("ix_job_sync_runs_ats_board_completed", table_name="job_sync_runs")
    op.drop_index("ix_job_sync_runs_status_started", table_name="job_sync_runs")
    op.drop_index("ix_job_sync_runs_provider_completed", table_name="job_sync_runs")
    op.drop_index("ix_job_sync_runs_sync_key_completed", table_name="job_sync_runs")
    op.drop_table("job_sync_runs")

    op.drop_index("uq_job_listing_sources_provider_job_id", table_name="job_listing_sources")
    op.drop_index("uq_job_listing_sources_greenhouse_identity", table_name="job_listing_sources")
    op.drop_index("ix_job_listing_sources_provider_query", table_name="job_listing_sources")
    op.drop_index("ix_job_listing_sources_provider_last_seen", table_name="job_listing_sources")
    op.drop_index("ix_job_listing_sources_ats_board_active", table_name="job_listing_sources")
    op.drop_index("ix_job_listing_sources_provider_active", table_name="job_listing_sources")
    op.drop_index("ix_job_listing_sources_job_listing", table_name="job_listing_sources")
    op.drop_table("job_listing_sources")

    op.drop_index("ix_job_listings_title", table_name="job_listings")
    op.drop_index("ix_job_listings_posting_date", table_name="job_listings")
    op.drop_index("ix_job_listings_remote_active", table_name="job_listings")
    op.drop_index("ix_job_listings_location_metro_active", table_name="job_listings")
    op.drop_index("ix_job_listings_location_active", table_name="job_listings")
    op.drop_index("ix_job_listings_company_name_active", table_name="job_listings")
    op.drop_index("ix_job_listings_company_active", table_name="job_listings")
    op.drop_index("ix_job_listings_active_source_updated", table_name="job_listings")
    op.drop_index("ix_job_listings_active_last_seen", table_name="job_listings")
    op.drop_table("job_listings")
