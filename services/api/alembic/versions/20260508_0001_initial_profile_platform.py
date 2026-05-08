"""Initial profile platform tables.

Revision ID: 20260508_0001
Revises:
Create Date: 2026-05-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260508_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
    )

    op.create_table(
        "candidate_profiles",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("headline", sa.String(length=300), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("profile_status", sa.String(length=40), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_candidate_profiles_tenant_slug"),
    )
    op.create_index("ix_candidate_profiles_slug", "candidate_profiles", ["slug"])

    op.create_table(
        "domains",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("candidate_profile_id", sa.String(length=36), sa.ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("purpose", sa.String(length=40), nullable=False, server_default="public_profile"),
        sa.Column("verification_status", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column("is_canonical", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("hostname", name="uq_domains_hostname"),
    )

    op.create_table(
        "role_targets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("candidate_profile_id", sa.String(length=36), sa.ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_titles", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("role_families", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("seniority", sa.String(length=80), nullable=True),
        sa.Column("preferred_locations", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("work_modes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("constraints", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "profile_facts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("candidate_profile_id", sa.String(length=36), sa.ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fact_type", sa.String(length=80), nullable=False),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("structured_value", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("visibility", sa.String(length=40), nullable=False, server_default="private"),
        sa.Column("verification_status", sa.String(length=40), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_profile_facts_profile_status", "profile_facts", ["candidate_profile_id", "verification_status", "visibility"])

    op.create_table(
        "profile_fact_drafts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("candidate_profile_id", sa.String(length=36), sa.ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("fact_type", sa.String(length=80), nullable=False),
        sa.Column("structured_value", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("confidence", sa.String(length=40), nullable=False, server_default="unknown"),
        sa.Column("suggested_visibility", sa.String(length=40), nullable=False, server_default="private"),
        sa.Column("review_status", sa.String(length=40), nullable=False, server_default="needs_review"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "skill_claims",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("candidate_profile_id", sa.String(length=36), sa.ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("skill_name", sa.String(length=160), nullable=False),
        sa.Column("skill_category", sa.String(length=120), nullable=False),
        sa.Column("years_min", sa.Integer(), nullable=True),
        sa.Column("years_max", sa.Integer(), nullable=True),
        sa.Column("recency", sa.String(length=80), nullable=True),
        sa.Column("proficiency", sa.String(length=80), nullable=True),
        sa.Column("evidence_fact_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("visibility", sa.String(length=40), nullable=False, server_default="private"),
        sa.Column("verification_status", sa.String(length=40), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_skill_claims_profile_skill", "skill_claims", ["candidate_profile_id", "skill_name"])

    op.create_table(
        "resume_artifacts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("candidate_profile_id", sa.String(length=36), sa.ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("storage_uri", sa.Text(), nullable=True),
        sa.Column("parse_status", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column("parsed_summary", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "profile_intake_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("candidate_profile_id", sa.String(length=36), sa.ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="active"),
        sa.Column("target_role_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("redacted_state", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "evidence_artifacts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("candidate_profile_id", sa.String(length=36), sa.ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("artifact_type", sa.String(length=80), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("uri", sa.Text(), nullable=True),
        sa.Column("visibility", sa.String(length=40), nullable=False, server_default="private"),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "usage_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("candidate_profile_id", sa.String(length=36), sa.ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=True),
        sa.Column("event_name", sa.String(length=120), nullable=False),
        sa.Column("event_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_usage_events_tenant_event", "usage_events", ["tenant_id", "event_name"])


def downgrade() -> None:
    op.drop_index("ix_usage_events_tenant_event", table_name="usage_events")
    op.drop_table("usage_events")
    op.drop_table("evidence_artifacts")
    op.drop_table("profile_intake_sessions")
    op.drop_table("resume_artifacts")
    op.drop_index("ix_skill_claims_profile_skill", table_name="skill_claims")
    op.drop_table("skill_claims")
    op.drop_table("profile_fact_drafts")
    op.drop_index("ix_profile_facts_profile_status", table_name="profile_facts")
    op.drop_table("profile_facts")
    op.drop_table("role_targets")
    op.drop_table("domains")
    op.drop_index("ix_candidate_profiles_slug", table_name="candidate_profiles")
    op.drop_table("candidate_profiles")
    op.drop_table("tenants")
