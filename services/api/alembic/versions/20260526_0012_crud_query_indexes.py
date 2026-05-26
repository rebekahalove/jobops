"""Add indexes for profile-scoped CRUD query paths.

Revision ID: 20260526_0012
Revises: 20260525_0011
Create Date: 2026-05-26
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "20260526_0012"
down_revision: str | None = "20260525_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_workspace_memberships_user_created", "workspace_memberships", ["user_id", "created_at"])
    op.create_index("ix_invite_tokens_username_active", "invite_tokens", ["username", "used_at", "revoked_at"])
    op.create_index("ix_user_sessions_user_revoked", "user_sessions", ["user_id", "revoked_at"])
    op.create_index("ix_user_sessions_tenant", "user_sessions", ["tenant_id"])
    op.create_index("ix_domains_candidate_profile", "domains", ["candidate_profile_id"])
    op.create_index("ix_candidate_profiles_tenant_created", "candidate_profiles", ["tenant_id", "created_at"])

    op.create_index(
        "ix_role_targets_session_active_updated",
        "role_targets",
        ["profile_intake_session_id", "is_active", "updated_at"],
    )
    op.create_index(
        "ix_role_targets_profile_publication_active",
        "role_targets",
        ["candidate_profile_id", "publication_status", "visibility", "is_active"],
    )
    op.create_index("ix_role_targets_profile_review", "role_targets", ["candidate_profile_id", "review_status"])

    op.create_index(
        "ix_profile_field_values_latest",
        "profile_field_values",
        ["candidate_profile_id", "field_group", "field_name", "lifecycle_status", "visibility", "updated_at"],
    )

    op.create_index("ix_target_companies_profile_created", "target_companies", ["candidate_profile_id", "created_at"])
    op.create_index(
        "ix_target_companies_profile_review_created",
        "target_companies",
        ["candidate_profile_id", "review_status", "created_at"],
    )
    op.create_index("ix_applications_profile_created", "applications", ["candidate_profile_id", "created_at"])

    op.create_index(
        "ix_profile_fact_drafts_session_created",
        "profile_fact_drafts",
        ["profile_intake_session_id", "created_at"],
    )
    op.create_index(
        "ix_profile_fact_drafts_profile_review",
        "profile_fact_drafts",
        ["candidate_profile_id", "review_status"],
    )

    op.create_index("ix_skill_claims_session_created", "skill_claims", ["profile_intake_session_id", "created_at"])
    op.create_index(
        "ix_skill_claims_profile_publication",
        "skill_claims",
        ["candidate_profile_id", "publication_status", "verification_status", "visibility", "skill_category", "skill_name"],
    )

    op.create_index("ix_resume_artifacts_profile_created", "resume_artifacts", ["candidate_profile_id", "created_at"])
    op.create_index(
        "ix_profile_intake_sessions_profile_status_created",
        "profile_intake_sessions",
        ["candidate_profile_id", "status", "created_at"],
    )
    op.create_index(
        "ix_profile_intake_sessions_profile_turn_created",
        "profile_intake_sessions",
        ["candidate_profile_id", "last_turn_at", "created_at"],
    )
    op.create_index(
        "ix_profile_intake_events_profile_created",
        "profile_intake_events",
        ["candidate_profile_id", "created_at"],
    )

    op.create_index(
        "ix_exp_project_drafts_session_created",
        "experience_project_drafts",
        ["profile_intake_session_id", "created_at"],
    )
    op.create_index(
        "ix_exp_project_drafts_profile_publication",
        "experience_project_drafts",
        ["candidate_profile_id", "publication_status", "visibility", "created_at"],
    )
    op.create_index(
        "ix_exp_project_drafts_profile_review",
        "experience_project_drafts",
        ["candidate_profile_id", "review_status", "created_at"],
    )

    op.create_index(
        "ix_evidence_artifacts_session_created",
        "evidence_artifacts",
        ["profile_intake_session_id", "created_at"],
    )
    op.create_index(
        "ix_evidence_artifacts_profile_publication",
        "evidence_artifacts",
        ["candidate_profile_id", "publication_status", "visibility", "created_at"],
    )
    op.create_index(
        "ix_evidence_artifacts_profile_review",
        "evidence_artifacts",
        ["candidate_profile_id", "review_status", "created_at"],
    )

    op.create_index("ix_usage_events_profile_created", "usage_events", ["candidate_profile_id", "created_at"])
    op.create_index(
        "ix_command_interaction_logs_profile_created",
        "command_interaction_logs",
        ["candidate_profile_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_command_interaction_logs_profile_created", table_name="command_interaction_logs")
    op.drop_index("ix_usage_events_profile_created", table_name="usage_events")

    op.drop_index("ix_evidence_artifacts_profile_review", table_name="evidence_artifacts")
    op.drop_index("ix_evidence_artifacts_profile_publication", table_name="evidence_artifacts")
    op.drop_index("ix_evidence_artifacts_session_created", table_name="evidence_artifacts")

    op.drop_index("ix_exp_project_drafts_profile_review", table_name="experience_project_drafts")
    op.drop_index("ix_exp_project_drafts_profile_publication", table_name="experience_project_drafts")
    op.drop_index("ix_exp_project_drafts_session_created", table_name="experience_project_drafts")

    op.drop_index("ix_profile_intake_events_profile_created", table_name="profile_intake_events")
    op.drop_index("ix_profile_intake_sessions_profile_turn_created", table_name="profile_intake_sessions")
    op.drop_index("ix_profile_intake_sessions_profile_status_created", table_name="profile_intake_sessions")
    op.drop_index("ix_resume_artifacts_profile_created", table_name="resume_artifacts")

    op.drop_index("ix_skill_claims_profile_publication", table_name="skill_claims")
    op.drop_index("ix_skill_claims_session_created", table_name="skill_claims")

    op.drop_index("ix_profile_fact_drafts_profile_review", table_name="profile_fact_drafts")
    op.drop_index("ix_profile_fact_drafts_session_created", table_name="profile_fact_drafts")

    op.drop_index("ix_applications_profile_created", table_name="applications")
    op.drop_index("ix_target_companies_profile_review_created", table_name="target_companies")
    op.drop_index("ix_target_companies_profile_created", table_name="target_companies")

    op.drop_index("ix_profile_field_values_latest", table_name="profile_field_values")

    op.drop_index("ix_role_targets_profile_review", table_name="role_targets")
    op.drop_index("ix_role_targets_profile_publication_active", table_name="role_targets")
    op.drop_index("ix_role_targets_session_active_updated", table_name="role_targets")

    op.drop_index("ix_candidate_profiles_tenant_created", table_name="candidate_profiles")
    op.drop_index("ix_domains_candidate_profile", table_name="domains")
    op.drop_index("ix_user_sessions_tenant", table_name="user_sessions")
    op.drop_index("ix_user_sessions_user_revoked", table_name="user_sessions")
    op.drop_index("ix_invite_tokens_username_active", table_name="invite_tokens")
    op.drop_index("ix_workspace_memberships_user_created", table_name="workspace_memberships")
