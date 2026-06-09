"""Add Job Sync location resolver tables.

Revision ID: 20260610_0028
Revises: 20260609_0027
Create Date: 2026-06-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260610_0028"
down_revision: str | None = "20260609_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_location_targets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("display_name", sa.String(length=240), nullable=False),
        sa.Column("normalized_key", sa.String(length=240), nullable=False),
        sa.Column("location_kind", sa.String(length=80), nullable=False, server_default="raw"),
        sa.Column("city", sa.String(length=160), nullable=True),
        sa.Column("region", sa.String(length=160), nullable=True),
        sa.Column("country_code", sa.String(length=16), nullable=True),
        sa.Column("country_name", sa.String(length=120), nullable=True),
        sa.Column("raw_inputs_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("confidence", sa.String(length=40), nullable=False, server_default="low"),
        sa.Column("verification_status", sa.String(length=40), nullable=False, server_default="needs_review"),
        sa.Column("source", sa.String(length=80), nullable=False, server_default="auto"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("normalized_key", name="uq_job_location_targets_normalized_key"),
    )
    op.create_index("ix_job_location_targets_normalized_key", "job_location_targets", ["normalized_key"])
    op.create_index("ix_job_location_targets_country_code", "job_location_targets", ["country_code"])
    op.create_index("ix_job_location_targets_verification_status", "job_location_targets", ["verification_status"])

    op.create_table(
        "job_provider_location_mappings",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "job_location_target_id",
            sa.String(length=36),
            sa.ForeignKey("job_location_targets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_name", sa.String(length=120), nullable=False),
        sa.Column("provider_country", sa.String(length=16), nullable=True),
        sa.Column("provider_where", sa.Text(), nullable=True),
        sa.Column("display_location", sa.String(length=240), nullable=False),
        sa.Column("confidence", sa.String(length=40), nullable=False, server_default="low"),
        sa.Column("verification_status", sa.String(length=40), nullable=False, server_default="needs_review"),
        sa.Column("source", sa.String(length=80), nullable=False, server_default="auto"),
        sa.Column("diagnostics_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "job_location_target_id",
            "provider_name",
            name="uq_job_provider_location_mappings_target_provider",
        ),
    )
    op.create_index(
        "ix_job_provider_location_mappings_provider_request",
        "job_provider_location_mappings",
        ["provider_name", "provider_country", "provider_where"],
    )
    op.create_index(
        "ix_job_provider_location_mappings_target",
        "job_provider_location_mappings",
        ["job_location_target_id"],
    )
    op.create_index(
        "ix_job_provider_location_mappings_verification_status",
        "job_provider_location_mappings",
        ["verification_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_job_provider_location_mappings_verification_status", table_name="job_provider_location_mappings")
    op.drop_index("ix_job_provider_location_mappings_target", table_name="job_provider_location_mappings")
    op.drop_index("ix_job_provider_location_mappings_provider_request", table_name="job_provider_location_mappings")
    op.drop_table("job_provider_location_mappings")
    op.drop_index("ix_job_location_targets_verification_status", table_name="job_location_targets")
    op.drop_index("ix_job_location_targets_country_code", table_name="job_location_targets")
    op.drop_index("ix_job_location_targets_normalized_key", table_name="job_location_targets")
    op.drop_table("job_location_targets")
