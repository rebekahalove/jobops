"""Extend candidate job list for synced listings and model rejections.

Revision ID: 20260611_0031
Revises: 20260610_0030
Create Date: 2026-06-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op


revision: str = "20260611_0031"
down_revision: str | None = "20260610_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    existing_columns = set()
    existing_indexes = set()
    existing_foreign_keys = set()
    existing_tables = set()
    job_id_nullable = False
    if not context.is_offline_mode():
        bind = op.get_bind()
        inspector = sa.inspect(bind)
        existing_tables = set(inspector.get_table_names())
        candidate_saved_job_columns = {column["name"]: column for column in inspector.get_columns("candidate_saved_jobs")}
        existing_columns = set(candidate_saved_job_columns)
        existing_indexes = {index["name"] for index in inspector.get_indexes("candidate_saved_jobs")}
        existing_foreign_keys = {fk["name"] for fk in inspector.get_foreign_keys("candidate_saved_jobs")}
        job_id_nullable = bool(candidate_saved_job_columns.get("job_id", {}).get("nullable"))

    with op.batch_alter_table("candidate_saved_jobs") as batch_op:
        if context.is_offline_mode() or not job_id_nullable:
            batch_op.alter_column("job_id", existing_type=sa.String(length=36), nullable=True)
        if context.is_offline_mode() or "job_listing_id" not in existing_columns:
            batch_op.add_column(sa.Column("job_listing_id", sa.String(length=36), nullable=True))
        if context.is_offline_mode() or "job_search_run_id" not in existing_columns:
            batch_op.add_column(sa.Column("job_search_run_id", sa.String(length=36), nullable=True))
        if context.is_offline_mode() or "last_model_reviewed_at" not in existing_columns:
            batch_op.add_column(sa.Column("last_model_reviewed_at", sa.DateTime(timezone=True), nullable=True))
        if context.is_offline_mode() or "model_selected_at" not in existing_columns:
            batch_op.add_column(sa.Column("model_selected_at", sa.DateTime(timezone=True), nullable=True))
        if context.is_offline_mode() or "model_rejected_at" not in existing_columns:
            batch_op.add_column(sa.Column("model_rejected_at", sa.DateTime(timezone=True), nullable=True))
        if context.is_offline_mode() or "model_decision_summary" not in existing_columns:
            batch_op.add_column(sa.Column("model_decision_summary", sa.Text(), nullable=True))
        if context.is_offline_mode() or "model_review_snapshot_json" not in existing_columns:
            batch_op.add_column(sa.Column("model_review_snapshot_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
        if context.is_offline_mode() or "fk_candidate_saved_jobs_job_listing_id" not in existing_foreign_keys:
            batch_op.create_foreign_key(
                "fk_candidate_saved_jobs_job_listing_id",
                "job_listings",
                ["job_listing_id"],
                ["id"],
                ondelete="CASCADE",
            )
        if context.is_offline_mode() or "fk_candidate_saved_jobs_job_search_run_id" not in existing_foreign_keys:
            batch_op.create_foreign_key(
                "fk_candidate_saved_jobs_job_search_run_id",
                "job_search_runs",
                ["job_search_run_id"],
                ["id"],
                ondelete="SET NULL",
            )
        if context.is_offline_mode() or "ix_candidate_saved_jobs_profile_status" not in existing_indexes:
            batch_op.create_index("ix_candidate_saved_jobs_profile_status", ["candidate_profile_id", "status"])
        if context.is_offline_mode() or "ix_candidate_saved_jobs_profile_listing" not in existing_indexes:
            batch_op.create_index("ix_candidate_saved_jobs_profile_listing", ["candidate_profile_id", "job_listing_id"])
        if context.is_offline_mode() or "ix_candidate_saved_jobs_job_listing" not in existing_indexes:
            batch_op.create_index("ix_candidate_saved_jobs_job_listing", ["job_listing_id"])
        if context.is_offline_mode() or "ix_candidate_saved_jobs_search_run" not in existing_indexes:
            batch_op.create_index("ix_candidate_saved_jobs_search_run", ["job_search_run_id"])
        if context.is_offline_mode() or "ix_candidate_saved_jobs_last_model_reviewed" not in existing_indexes:
            batch_op.create_index("ix_candidate_saved_jobs_last_model_reviewed", ["last_model_reviewed_at"])
        if context.is_offline_mode() or "uq_candidate_saved_jobs_profile_listing" not in existing_indexes:
            batch_op.create_index(
                "uq_candidate_saved_jobs_profile_listing",
                ["candidate_profile_id", "job_listing_id"],
                unique=True,
                sqlite_where=sa.text("job_listing_id IS NOT NULL"),
                postgresql_where=sa.text("job_listing_id IS NOT NULL"),
            )

    if context.is_offline_mode() or "candidate_job_rejection_reasons" not in existing_tables:
        op.create_table(
            "candidate_job_rejection_reasons",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "candidate_job_id",
                sa.String(length=36),
                sa.ForeignKey("candidate_saved_jobs.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("reason_code", sa.String(length=80), nullable=False),
            sa.Column("affected_field", sa.String(length=160), nullable=True),
            sa.Column("explanation", sa.Text(), nullable=True),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("reset_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reset_reason", sa.Text(), nullable=True),
            sa.Column("reset_by", sa.String(length=200), nullable=True),
        )
    rejection_indexes = set()
    if not context.is_offline_mode():
        rejection_indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("candidate_job_rejection_reasons")}
    if context.is_offline_mode() or "ix_candidate_job_rejection_reasons_candidate_job" not in rejection_indexes:
        op.create_index(
            "ix_candidate_job_rejection_reasons_candidate_job",
            "candidate_job_rejection_reasons",
            ["candidate_job_id", "active"],
        )
    if context.is_offline_mode() or "ix_candidate_job_rejection_reasons_reason_active" not in rejection_indexes:
        op.create_index(
            "ix_candidate_job_rejection_reasons_reason_active",
            "candidate_job_rejection_reasons",
            ["reason_code", "active"],
        )


def downgrade() -> None:
    if not context.is_offline_mode():
        bind = op.get_bind()
        synced_saved_jobs = bind.execute(
            sa.text("SELECT count(*) FROM candidate_saved_jobs WHERE job_id IS NULL OR job_listing_id IS NOT NULL")
        ).scalar()
        rejection_reasons = bind.execute(sa.text("SELECT count(*) FROM candidate_job_rejection_reasons")).scalar()
        if synced_saved_jobs or rejection_reasons:
            return

    op.drop_index("ix_candidate_job_rejection_reasons_reason_active", table_name="candidate_job_rejection_reasons")
    op.drop_index("ix_candidate_job_rejection_reasons_candidate_job", table_name="candidate_job_rejection_reasons")
    op.drop_table("candidate_job_rejection_reasons")

    existing_indexes = set()
    existing_foreign_keys = set()
    if not context.is_offline_mode():
        bind = op.get_bind()
        existing_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("candidate_saved_jobs")}
        existing_foreign_keys = {fk["name"] for fk in sa.inspect(bind).get_foreign_keys("candidate_saved_jobs")}
    with op.batch_alter_table("candidate_saved_jobs") as batch_op:
        for index_name in (
            "uq_candidate_saved_jobs_profile_listing",
            "ix_candidate_saved_jobs_last_model_reviewed",
            "ix_candidate_saved_jobs_search_run",
            "ix_candidate_saved_jobs_job_listing",
            "ix_candidate_saved_jobs_profile_listing",
            "ix_candidate_saved_jobs_profile_status",
        ):
            if context.is_offline_mode() or index_name in existing_indexes:
                batch_op.drop_index(index_name)
        for constraint_name in (
            "fk_candidate_saved_jobs_job_search_run_id",
            "fk_candidate_saved_jobs_job_listing_id",
        ):
            if context.is_offline_mode() or constraint_name in existing_foreign_keys:
                batch_op.drop_constraint(constraint_name, type_="foreignkey")
        batch_op.drop_column("model_review_snapshot_json")
        batch_op.drop_column("model_decision_summary")
        batch_op.drop_column("model_rejected_at")
        batch_op.drop_column("model_selected_at")
        batch_op.drop_column("last_model_reviewed_at")
        batch_op.drop_column("job_search_run_id")
        batch_op.drop_column("job_listing_id")
        batch_op.alter_column("job_id", existing_type=sa.String(length=36), nullable=False)
