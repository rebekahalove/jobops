"""Add archive metadata for saved jobs and applications.

Revision ID: 20260531_0022
Revises: 20260531_0021
Create Date: 2026-05-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op


revision: str = "20260531_0022"
down_revision: str | None = "20260531_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if context.is_offline_mode():
        with op.batch_alter_table("candidate_saved_jobs") as batch_op:
            batch_op.add_column(sa.Column("archived_reason", sa.String(length=120), nullable=True))
            batch_op.add_column(sa.Column("archived_by_action", sa.String(length=120), nullable=True))
        with op.batch_alter_table("applications") as batch_op:
            batch_op.add_column(sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
            batch_op.add_column(sa.Column("archived_reason", sa.String(length=120), nullable=True))
            batch_op.add_column(sa.Column("archived_by_action", sa.String(length=120), nullable=True))
            batch_op.create_unique_constraint("uq_applications_profile_job", ["candidate_profile_id", "job_id"])
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    saved_job_columns = {column["name"] for column in inspector.get_columns("candidate_saved_jobs")}
    application_columns = {column["name"] for column in inspector.get_columns("applications")}
    application_constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("applications")}

    with op.batch_alter_table("candidate_saved_jobs") as batch_op:
        if "archived_reason" not in saved_job_columns:
            batch_op.add_column(sa.Column("archived_reason", sa.String(length=120), nullable=True))
        if "archived_by_action" not in saved_job_columns:
            batch_op.add_column(sa.Column("archived_by_action", sa.String(length=120), nullable=True))

    with op.batch_alter_table("applications") as batch_op:
        if "archived_at" not in application_columns:
            batch_op.add_column(sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
        if "archived_reason" not in application_columns:
            batch_op.add_column(sa.Column("archived_reason", sa.String(length=120), nullable=True))
        if "archived_by_action" not in application_columns:
            batch_op.add_column(sa.Column("archived_by_action", sa.String(length=120), nullable=True))
        if "uq_applications_profile_job" not in application_constraints:
            batch_op.create_unique_constraint("uq_applications_profile_job", ["candidate_profile_id", "job_id"])


def downgrade() -> None:
    if context.is_offline_mode():
        with op.batch_alter_table("applications") as batch_op:
            batch_op.drop_constraint("uq_applications_profile_job", type_="unique")
            batch_op.drop_column("archived_by_action")
            batch_op.drop_column("archived_reason")
            batch_op.drop_column("archived_at")
        with op.batch_alter_table("candidate_saved_jobs") as batch_op:
            batch_op.drop_column("archived_by_action")
            batch_op.drop_column("archived_reason")
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    saved_job_columns = {column["name"] for column in inspector.get_columns("candidate_saved_jobs")}
    application_columns = {column["name"] for column in inspector.get_columns("applications")}
    application_constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("applications")}

    with op.batch_alter_table("applications") as batch_op:
        if "uq_applications_profile_job" in application_constraints:
            batch_op.drop_constraint("uq_applications_profile_job", type_="unique")
        if "archived_by_action" in application_columns:
            batch_op.drop_column("archived_by_action")
        if "archived_reason" in application_columns:
            batch_op.drop_column("archived_reason")
        if "archived_at" in application_columns:
            batch_op.drop_column("archived_at")

    with op.batch_alter_table("candidate_saved_jobs") as batch_op:
        if "archived_by_action" in saved_job_columns:
            batch_op.drop_column("archived_by_action")
        if "archived_reason" in saved_job_columns:
            batch_op.drop_column("archived_reason")
