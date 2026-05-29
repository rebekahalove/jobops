"""Add canonical jobs and saved-job links.

Revision ID: 20260528_0014
Revises: 20260526_0013
Create Date: 2026-05-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260528_0014"
down_revision: str | None = "20260526_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_postings",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=True),
        sa.Column("company_name", sa.String(length=240), nullable=False),
        sa.Column("job_url", sa.Text(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=True),
        sa.Column("apply_url", sa.Text(), nullable=True),
        sa.Column("normalized_url", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=120), nullable=True),
        sa.Column("location", sa.String(length=240), nullable=True),
        sa.Column("remote_work_mode", sa.String(length=80), nullable=True),
        sa.Column("employment_type", sa.String(length=120), nullable=True),
        sa.Column("salary_text", sa.Text(), nullable=True),
        sa.Column("description_excerpt", sa.Text(), nullable=True),
        sa.Column("discovered_by", sa.String(length=120), nullable=True),
        sa.Column("posting_date", sa.Date(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("normalized_url", name="uq_job_postings_normalized_url"),
    )
    op.create_index("ix_job_postings_company_title", "job_postings", ["company_name", "title"])
    op.create_index("ix_job_postings_last_seen", "job_postings", ["last_seen_at"])

    op.create_table(
        "candidate_saved_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("candidate_profile_id", sa.String(length=36), sa.ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.String(length=36), sa.ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="saved"),
        sa.Column("fit_summary", sa.Text(), nullable=True),
        sa.Column("user_notes", sa.Text(), nullable=True),
        sa.Column("source_command", sa.Text(), nullable=True),
        sa.Column("discovery_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("candidate_profile_id", "job_id", name="uq_candidate_saved_jobs_profile_job"),
    )
    op.create_index("ix_candidate_saved_jobs_profile_added", "candidate_saved_jobs", ["candidate_profile_id", "added_at"])
    op.create_index("ix_candidate_saved_jobs_profile_status_added", "candidate_saved_jobs", ["candidate_profile_id", "status", "added_at"])


def downgrade() -> None:
    op.drop_index("ix_candidate_saved_jobs_profile_status_added", table_name="candidate_saved_jobs")
    op.drop_index("ix_candidate_saved_jobs_profile_added", table_name="candidate_saved_jobs")
    op.drop_table("candidate_saved_jobs")
    op.drop_index("ix_job_postings_last_seen", table_name="job_postings")
    op.drop_index("ix_job_postings_company_title", table_name="job_postings")
    op.drop_table("job_postings")
