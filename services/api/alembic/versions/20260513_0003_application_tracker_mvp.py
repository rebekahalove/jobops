"""Add manual application tracker tables.

Revision ID: 20260513_0003
Revises: 20260513_0002
Create Date: 2026-05-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260513_0003"
down_revision: str | None = "20260513_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "target_companies",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("candidate_profile_id", sa.String(length=36), sa.ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("website_url", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("candidate_profile_id", "name", name="uq_target_companies_profile_name"),
    )
    op.create_index("ix_target_companies_profile_name", "target_companies", ["candidate_profile_id", "name"])

    op.create_table(
        "job_roles",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("candidate_profile_id", sa.String(length=36), sa.ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_company_id", sa.String(length=36), sa.ForeignKey("target_companies.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("job_url", sa.Text(), nullable=True),
        sa.Column("location", sa.String(length=240), nullable=True),
        sa.Column("source", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="saved"),
        sa.Column("raw_description_artifact_uri", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_job_roles_company_title", "job_roles", ["target_company_id", "title"])
    op.create_index("ix_job_roles_profile_status", "job_roles", ["candidate_profile_id", "status"])

    op.create_table(
        "applications",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("candidate_profile_id", sa.String(length=36), sa.ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_company_id", sa.String(length=36), sa.ForeignKey("target_companies.id", ondelete="SET NULL"), nullable=True),
        sa.Column("job_role_id", sa.String(length=36), sa.ForeignKey("job_roles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("company_name", sa.String(length=240), nullable=False),
        sa.Column("job_title", sa.String(length=240), nullable=False),
        sa.Column("job_url", sa.Text(), nullable=True),
        sa.Column("location", sa.String(length=240), nullable=True),
        sa.Column("source", sa.String(length=120), nullable=True),
        sa.Column("date_applied", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="saved"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("next_follow_up_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_applications_next_follow_up", "applications", ["candidate_profile_id", "next_follow_up_date"])
    op.create_index("ix_applications_profile_status", "applications", ["candidate_profile_id", "status"])

    op.create_table(
        "application_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("application_id", sa.String(length=36), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_application_events_application_date", "application_events", ["application_id", "event_date"])


def downgrade() -> None:
    op.drop_index("ix_application_events_application_date", table_name="application_events")
    op.drop_table("application_events")
    op.drop_index("ix_applications_profile_status", table_name="applications")
    op.drop_index("ix_applications_next_follow_up", table_name="applications")
    op.drop_table("applications")
    op.drop_index("ix_job_roles_profile_status", table_name="job_roles")
    op.drop_index("ix_job_roles_company_title", table_name="job_roles")
    op.drop_table("job_roles")
    op.drop_index("ix_target_companies_profile_name", table_name="target_companies")
    op.drop_table("target_companies")
