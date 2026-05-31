"""Add global job page extractions.

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
        create_job_page_extractions_table()
        return

    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    if "job_page_extractions" not in existing_tables:
        create_job_page_extractions_table()


def downgrade() -> None:
    if context.is_offline_mode():
        drop_job_page_extractions_table()
        return

    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    if "job_page_extractions" in existing_tables:
        drop_job_page_extractions_table()


def create_job_page_extractions_table() -> None:
    op.create_table(
        "job_page_extractions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("final_url", sa.Text(), nullable=True),
        sa.Column("platform", sa.String(length=40), nullable=False),
        sa.Column("extraction_status", sa.String(length=60), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("stale_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("page_title", sa.Text(), nullable=True),
        sa.Column("required_materials", sa.JSON(), nullable=False),
        sa.Column("optional_materials", sa.JSON(), nullable=False),
        sa.Column("application_fields", sa.JSON(), nullable=False),
        sa.Column("screening_questions", sa.JSON(), nullable=False),
        sa.Column("detected_requirements", sa.JSON(), nullable=False),
        sa.Column("extraction_summary", sa.Text(), nullable=True),
        sa.Column("confidence", sa.String(length=20), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("raw_text_excerpt", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["job_postings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_page_extractions_job_fetched", "job_page_extractions", ["job_id", "fetched_at"])
    op.create_index(
        "ix_job_page_extractions_job_status",
        "job_page_extractions",
        ["job_id", "extraction_status", "fetched_at"],
    )


def drop_job_page_extractions_table() -> None:
    op.drop_index("ix_job_page_extractions_job_status", table_name="job_page_extractions")
    op.drop_index("ix_job_page_extractions_job_fetched", table_name="job_page_extractions")
    op.drop_table("job_page_extractions")
