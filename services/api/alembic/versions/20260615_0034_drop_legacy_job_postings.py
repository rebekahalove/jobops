"""Drop legacy job_postings schema.

Revision ID: 20260615_0034
Revises: 20260613_0033
Create Date: 2026-06-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op


revision: str = "20260615_0034"
down_revision: str | None = "20260613_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if table_exists("candidate_saved_jobs") and column_exists("candidate_saved_jobs", "job_id"):
        with op.batch_alter_table("candidate_saved_jobs") as batch_op:
            drop_foreign_keys_for_column(batch_op, "candidate_saved_jobs", "job_id")
            drop_unique_constraint_if_exists(batch_op, "candidate_saved_jobs", "uq_candidate_saved_jobs_profile_job")
            batch_op.drop_column("job_id")

    if table_exists("applications") and column_exists("applications", "job_id"):
        drop_index_if_exists("ix_applications_profile_job", "applications")
        with op.batch_alter_table("applications") as batch_op:
            drop_foreign_keys_for_column(batch_op, "applications", "job_id")
            drop_unique_constraint_if_exists(batch_op, "applications", "uq_applications_profile_job")
            batch_op.drop_column("job_id")

    if table_exists("job_postings"):
        drop_index_if_exists("ix_job_postings_last_seen", "job_postings")
        drop_index_if_exists("ix_job_postings_company_title", "job_postings")
        op.drop_table("job_postings")


def downgrade() -> None:
    # This downgrade recreates only an empty legacy schema shape. The upgrade
    # intentionally deletes legacy job_postings data and job_id links.
    if not table_exists("job_postings"):
        op.create_table(
            "job_postings",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("company_id", sa.String(length=36), sa.ForeignKey("companies.id", ondelete="SET NULL"), nullable=True),
            sa.Column("company_name", sa.String(length=240), nullable=False),
            sa.Column("job_url", sa.Text(), nullable=False),
            sa.Column("canonical_url", sa.Text(), nullable=True),
            sa.Column("apply_url", sa.Text(), nullable=True),
            sa.Column("normalized_url", sa.Text(), nullable=False),
            sa.Column("source", sa.String(length=120), nullable=True),
            sa.Column("source_provider", sa.String(length=120), nullable=True),
            sa.Column("provider_type", sa.String(length=60), nullable=True),
            sa.Column("source_result_id", sa.String(length=240), nullable=True),
            sa.Column("source_query", sa.Text(), nullable=True),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("provider_raw_metadata", sa.JSON(), nullable=True),
            sa.Column("company_website_url", sa.Text(), nullable=True),
            sa.Column("company_careers_url", sa.Text(), nullable=True),
            sa.Column("ats_provider", sa.String(length=80), nullable=True),
            sa.Column("ats_board_token", sa.String(length=240), nullable=True),
            sa.Column("provenance", sa.String(length=40), nullable=False, server_default="unknown"),
            sa.Column("location", sa.String(length=240), nullable=True),
            sa.Column("remote_work_mode", sa.String(length=80), nullable=True),
            sa.Column("employment_type", sa.String(length=120), nullable=True),
            sa.Column("salary_min", sa.Integer(), nullable=True),
            sa.Column("salary_max", sa.Integer(), nullable=True),
            sa.Column("salary_currency", sa.String(length=3), nullable=True),
            sa.Column("salary_text", sa.Text(), nullable=True),
            sa.Column("full_description", sa.Text(), nullable=True),
            sa.Column("description_excerpt", sa.Text(), nullable=True),
            sa.Column("discovered_by", sa.String(length=120), nullable=True),
            sa.Column("url_verification_status", sa.String(length=60), nullable=False, server_default="unverified"),
            sa.Column("url_verification_checked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("url_verification_summary", sa.Text(), nullable=True),
            sa.Column("posting_date", sa.Date(), nullable=True),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("normalized_url", name="uq_job_postings_normalized_url"),
        )
        op.create_index("ix_job_postings_company_title", "job_postings", ["company_name", "title"])
        op.create_index("ix_job_postings_last_seen", "job_postings", ["last_seen_at"])

    if table_exists("candidate_saved_jobs") and not column_exists("candidate_saved_jobs", "job_id"):
        with op.batch_alter_table("candidate_saved_jobs") as batch_op:
            batch_op.add_column(sa.Column("job_id", sa.String(length=36), nullable=True))
            batch_op.create_foreign_key(
                "fk_candidate_saved_jobs_job_id_job_postings",
                "job_postings",
                ["job_id"],
                ["id"],
                ondelete="CASCADE",
            )
            batch_op.create_unique_constraint("uq_candidate_saved_jobs_profile_job", ["candidate_profile_id", "job_id"])

    if table_exists("applications") and not column_exists("applications", "job_id"):
        with op.batch_alter_table("applications") as batch_op:
            batch_op.add_column(sa.Column("job_id", sa.String(length=36), nullable=True))
            batch_op.create_foreign_key(
                "fk_applications_job_id_job_postings",
                "job_postings",
                ["job_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch_op.create_unique_constraint("uq_applications_profile_job", ["candidate_profile_id", "job_id"])
            batch_op.create_index("ix_applications_profile_job", ["candidate_profile_id", "job_id"])


def table_exists(table_name: str) -> bool:
    if context.is_offline_mode():
        return True
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def column_exists(table_name: str, column_name: str) -> bool:
    if context.is_offline_mode():
        return True
    return column_name in {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def drop_unique_constraint_if_exists(batch_op, table_name: str, constraint_name: str) -> None:
    if context.is_offline_mode() or constraint_name in unique_constraint_names(table_name):
        batch_op.drop_constraint(constraint_name, type_="unique")


def drop_foreign_keys_for_column(batch_op, table_name: str, column_name: str) -> None:
    if context.is_offline_mode():
        return
    for foreign_key in sa.inspect(op.get_bind()).get_foreign_keys(table_name):
        if foreign_key.get("constrained_columns") == [column_name] and foreign_key.get("name"):
            batch_op.drop_constraint(str(foreign_key["name"]), type_="foreignkey")


def drop_index_if_exists(index_name: str, table_name: str) -> None:
    if context.is_offline_mode() or index_name in index_names(table_name):
        op.drop_index(index_name, table_name=table_name)


def unique_constraint_names(table_name: str) -> set[str]:
    if not table_exists(table_name):
        return set()
    return {constraint["name"] for constraint in sa.inspect(op.get_bind()).get_unique_constraints(table_name) if constraint.get("name")}


def index_names(table_name: str) -> set[str]:
    if not table_exists(table_name):
        return set()
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name) if index.get("name")}
