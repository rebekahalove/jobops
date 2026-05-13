"""Add profile intake persistence tables and draft links.

Revision ID: 20260513_0002
Revises: 20260508_0001
Create Date: 2026-05-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260513_0002"
down_revision: str | None = "20260508_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("profile_intake_sessions", sa.Column("last_turn_at", sa.DateTime(timezone=True), nullable=True))

    with op.batch_alter_table("role_targets") as batch_op:
        batch_op.add_column(sa.Column("profile_intake_session_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("source", sa.String(length=40), nullable=False, server_default="model"))
        batch_op.add_column(sa.Column("review_status", sa.String(length=40), nullable=False, server_default="needs_review"))
        batch_op.add_column(sa.Column("visibility", sa.String(length=40), nullable=False, server_default="private"))
        batch_op.add_column(sa.Column("publication_status", sa.String(length=40), nullable=False, server_default="not_published"))
        batch_op.create_foreign_key(
            "fk_role_targets_profile_intake_session_id",
            "profile_intake_sessions",
            ["profile_intake_session_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("profile_fact_drafts") as batch_op:
        batch_op.add_column(sa.Column("profile_intake_session_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_profile_fact_drafts_profile_intake_session_id",
            "profile_intake_sessions",
            ["profile_intake_session_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("skill_claims") as batch_op:
        batch_op.add_column(sa.Column("profile_intake_session_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("source", sa.String(length=40), nullable=False, server_default="model"))
        batch_op.add_column(sa.Column("evidence_summary", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("publication_status", sa.String(length=40), nullable=False, server_default="not_published"))
        batch_op.create_foreign_key(
            "fk_skill_claims_profile_intake_session_id",
            "profile_intake_sessions",
            ["profile_intake_session_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("evidence_artifacts") as batch_op:
        batch_op.add_column(sa.Column("profile_intake_session_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("source", sa.String(length=40), nullable=False, server_default="model"))
        batch_op.add_column(sa.Column("review_status", sa.String(length=40), nullable=False, server_default="needs_review"))
        batch_op.add_column(sa.Column("publication_status", sa.String(length=40), nullable=False, server_default="not_published"))
        batch_op.create_foreign_key(
            "fk_evidence_artifacts_profile_intake_session_id",
            "profile_intake_sessions",
            ["profile_intake_session_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_table(
        "profile_intake_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("session_id", sa.String(length=36), sa.ForeignKey("profile_intake_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("candidate_profile_id", sa.String(length=36), sa.ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("redacted_text", sa.Text(), nullable=True),
        sa.Column("raw_text_artifact_path", sa.Text(), nullable=True),
        sa.Column("model_run_id", sa.String(length=120), nullable=True),
        sa.Column("event_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_profile_intake_events_session_created", "profile_intake_events", ["session_id", "created_at"])

    op.create_table(
        "experience_project_drafts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("candidate_profile_id", sa.String(length=36), sa.ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "profile_intake_session_id",
            sa.String(length=36),
            sa.ForeignKey("profile_intake_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("organization", sa.String(length=200), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False, server_default="model"),
        sa.Column("visibility", sa.String(length=40), nullable=False, server_default="private"),
        sa.Column("review_status", sa.String(length=40), nullable=False, server_default="needs_review"),
        sa.Column("publication_status", sa.String(length=40), nullable=False, server_default="not_published"),
        sa.Column("structured_value", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_experience_project_drafts_session", "experience_project_drafts", ["profile_intake_session_id"])


def downgrade() -> None:
    op.drop_index("ix_experience_project_drafts_session", table_name="experience_project_drafts")
    op.drop_table("experience_project_drafts")
    op.drop_index("ix_profile_intake_events_session_created", table_name="profile_intake_events")
    op.drop_table("profile_intake_events")

    with op.batch_alter_table("evidence_artifacts") as batch_op:
        batch_op.drop_constraint("fk_evidence_artifacts_profile_intake_session_id", type_="foreignkey")
        batch_op.drop_column("publication_status")
        batch_op.drop_column("review_status")
        batch_op.drop_column("source")
        batch_op.drop_column("profile_intake_session_id")

    with op.batch_alter_table("skill_claims") as batch_op:
        batch_op.drop_constraint("fk_skill_claims_profile_intake_session_id", type_="foreignkey")
        batch_op.drop_column("publication_status")
        batch_op.drop_column("evidence_summary")
        batch_op.drop_column("source")
        batch_op.drop_column("profile_intake_session_id")

    with op.batch_alter_table("profile_fact_drafts") as batch_op:
        batch_op.drop_constraint("fk_profile_fact_drafts_profile_intake_session_id", type_="foreignkey")
        batch_op.drop_column("profile_intake_session_id")

    with op.batch_alter_table("role_targets") as batch_op:
        batch_op.drop_constraint("fk_role_targets_profile_intake_session_id", type_="foreignkey")
        batch_op.drop_column("publication_status")
        batch_op.drop_column("visibility")
        batch_op.drop_column("review_status")
        batch_op.drop_column("source")
        batch_op.drop_column("profile_intake_session_id")

    op.drop_column("profile_intake_sessions", "last_turn_at")
