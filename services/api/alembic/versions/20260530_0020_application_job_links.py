"""Link applications to canonical saved jobs.

Revision ID: 20260530_0020
Revises: 20260529_0019
Create Date: 2026-05-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from alembic import context


revision: str = "20260530_0020"
down_revision: str | None = "20260529_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if context.is_offline_mode():
        with op.batch_alter_table("applications") as batch_op:
            batch_op.add_column(sa.Column("job_id", sa.String(length=36), nullable=True))
            batch_op.add_column(sa.Column("saved_job_id", sa.String(length=36), nullable=True))
            batch_op.create_foreign_key("fk_applications_job_id_job_postings", "job_postings", ["job_id"], ["id"], ondelete="SET NULL")
            batch_op.create_foreign_key(
                "fk_applications_saved_job_id_candidate_saved_jobs",
                "candidate_saved_jobs",
                ["saved_job_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch_op.create_index("ix_applications_profile_job", ["candidate_profile_id", "job_id"])
            batch_op.create_index("ix_applications_saved_job", ["saved_job_id"])
        return

    bind = op.get_bind()
    existing_columns = {column["name"] for column in sa.inspect(bind).get_columns("applications")}

    with op.batch_alter_table("applications") as batch_op:
        if "job_id" not in existing_columns:
            batch_op.add_column(sa.Column("job_id", sa.String(length=36), nullable=True))
        if "saved_job_id" not in existing_columns:
            batch_op.add_column(sa.Column("saved_job_id", sa.String(length=36), nullable=True))

    existing_foreign_keys = {fk["name"] for fk in sa.inspect(bind).get_foreign_keys("applications")}
    existing_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("applications")}

    with op.batch_alter_table("applications") as batch_op:
        if "fk_applications_job_id_job_postings" not in existing_foreign_keys:
            batch_op.create_foreign_key("fk_applications_job_id_job_postings", "job_postings", ["job_id"], ["id"], ondelete="SET NULL")
        if "fk_applications_saved_job_id_candidate_saved_jobs" not in existing_foreign_keys:
            batch_op.create_foreign_key(
                "fk_applications_saved_job_id_candidate_saved_jobs",
                "candidate_saved_jobs",
                ["saved_job_id"],
                ["id"],
                ondelete="SET NULL",
            )
        if "ix_applications_profile_job" not in existing_indexes:
            batch_op.create_index("ix_applications_profile_job", ["candidate_profile_id", "job_id"])
        if "ix_applications_saved_job" not in existing_indexes:
            batch_op.create_index("ix_applications_saved_job", ["saved_job_id"])


def downgrade() -> None:
    if context.is_offline_mode():
        with op.batch_alter_table("applications") as batch_op:
            batch_op.drop_index("ix_applications_saved_job")
            batch_op.drop_index("ix_applications_profile_job")
            batch_op.drop_constraint("fk_applications_saved_job_id_candidate_saved_jobs", type_="foreignkey")
            batch_op.drop_constraint("fk_applications_job_id_job_postings", type_="foreignkey")
            batch_op.drop_column("saved_job_id")
            batch_op.drop_column("job_id")
        return

    bind = op.get_bind()
    existing_columns = {column["name"] for column in sa.inspect(bind).get_columns("applications")}
    existing_foreign_keys = {fk["name"] for fk in sa.inspect(bind).get_foreign_keys("applications")}
    existing_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("applications")}

    with op.batch_alter_table("applications") as batch_op:
        if "ix_applications_saved_job" in existing_indexes:
            batch_op.drop_index("ix_applications_saved_job")
        if "ix_applications_profile_job" in existing_indexes:
            batch_op.drop_index("ix_applications_profile_job")
        if "fk_applications_saved_job_id_candidate_saved_jobs" in existing_foreign_keys:
            batch_op.drop_constraint("fk_applications_saved_job_id_candidate_saved_jobs", type_="foreignkey")
        if "fk_applications_job_id_job_postings" in existing_foreign_keys:
            batch_op.drop_constraint("fk_applications_job_id_job_postings", type_="foreignkey")
        if "saved_job_id" in existing_columns:
            batch_op.drop_column("saved_job_id")
        if "job_id" in existing_columns:
            batch_op.drop_column("job_id")
