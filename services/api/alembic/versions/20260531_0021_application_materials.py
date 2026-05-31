"""Add application material bundles.

Revision ID: 20260531_0021
Revises: 20260530_0020
Create Date: 2026-05-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op


revision: str = "20260531_0021"
down_revision: str | None = "20260530_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if context.is_offline_mode():
        with op.batch_alter_table("job_postings") as batch_op:
            batch_op.add_column(sa.Column("full_description", sa.Text(), nullable=True))
        create_material_tables()
        return

    bind = op.get_bind()
    existing_job_columns = {column["name"] for column in sa.inspect(bind).get_columns("job_postings")}
    existing_tables = set(sa.inspect(bind).get_table_names())

    with op.batch_alter_table("job_postings") as batch_op:
        if "full_description" not in existing_job_columns:
            batch_op.add_column(sa.Column("full_description", sa.Text(), nullable=True))

    if "application_material_bundles" not in existing_tables:
        create_material_tables()


def downgrade() -> None:
    if context.is_offline_mode():
        op.drop_index("ix_application_material_items_bundle_sort", table_name="application_material_items")
        op.drop_table("application_material_items")
        op.drop_index("ix_application_material_bundles_profile_created", table_name="application_material_bundles")
        op.drop_index("ix_application_material_bundles_application_created", table_name="application_material_bundles")
        op.drop_table("application_material_bundles")
        with op.batch_alter_table("job_postings") as batch_op:
            batch_op.drop_column("full_description")
        return

    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    if "application_material_items" in existing_tables:
        op.drop_index("ix_application_material_items_bundle_sort", table_name="application_material_items")
        op.drop_table("application_material_items")
    if "application_material_bundles" in existing_tables:
        op.drop_index("ix_application_material_bundles_profile_created", table_name="application_material_bundles")
        op.drop_index("ix_application_material_bundles_application_created", table_name="application_material_bundles")
        op.drop_table("application_material_bundles")

    existing_job_columns = {column["name"] for column in sa.inspect(bind).get_columns("job_postings")}
    if "full_description" in existing_job_columns:
        with op.batch_alter_table("job_postings") as batch_op:
            batch_op.drop_column("full_description")


def create_material_tables() -> None:
    op.create_table(
        "application_material_bundles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("application_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_profile_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("source_context_snapshot", sa.JSON(), nullable=False),
        sa.Column("model_provider", sa.String(length=120), nullable=True),
        sa.Column("model_name", sa.String(length=240), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_profile_id"], ["candidate_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_application_material_bundles_application_created",
        "application_material_bundles",
        ["application_id", "created_at"],
    )
    op.create_index(
        "ix_application_material_bundles_profile_created",
        "application_material_bundles",
        ["candidate_profile_id", "created_at"],
    )
    op.create_table(
        "application_material_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("bundle_id", sa.String(length=36), nullable=False),
        sa.Column("material_type", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_format", sa.String(length=40), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["bundle_id"], ["application_material_bundles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_application_material_items_bundle_sort",
        "application_material_items",
        ["bundle_id", "sort_order"],
    )
