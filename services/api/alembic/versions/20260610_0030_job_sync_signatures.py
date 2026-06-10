"""Add durable Job Sync signatures.

Revision ID: 20260610_0030
Revises: 20260610_0029
Create Date: 2026-06-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op


revision: str = "20260610_0030"
down_revision: str | None = "20260610_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_sync_signatures",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("provider_name", sa.String(length=120), nullable=False),
        sa.Column("provider_type", sa.String(length=60), nullable=False),
        sa.Column("sync_kind", sa.String(length=80), nullable=False),
        sa.Column("sync_key", sa.Text(), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("query_kind", sa.String(length=80), nullable=False, server_default="manual"),
        sa.Column("job_location_target_id", sa.String(length=36), sa.ForeignKey("job_location_targets.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "job_provider_location_mapping_id",
            sa.String(length=36),
            sa.ForeignKey("job_provider_location_mappings.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("provider_country", sa.String(length=16), nullable=True),
        sa.Column("provider_where", sa.Text(), nullable=True),
        sa.Column("display_location", sa.Text(), nullable=True),
        sa.Column("normalized_location_key", sa.String(length=240), nullable=True),
        sa.Column("results_per_page", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("max_pages", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("freshness_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("verification_status", sa.String(length=40), nullable=False, server_default="verified"),
        sa.Column("source", sa.String(length=80), nullable=False, server_default="cli"),
        sa.Column("created_by", sa.String(length=200), nullable=True),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=40), nullable=True),
        sa.Column("last_raw_result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_normalized_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_created_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_updated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("criteria_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("sync_key", name="uq_job_sync_signatures_sync_key"),
    )
    op.create_index("ix_job_sync_signatures_provider_enabled", "job_sync_signatures", ["provider_name", "enabled"])
    op.create_index("ix_job_sync_signatures_provider_completed", "job_sync_signatures", ["provider_name", "last_completed_at"])
    op.create_index(
        "ix_job_sync_signatures_provider_request",
        "job_sync_signatures",
        ["provider_name", "provider_country", "provider_where", "query_text"],
    )
    op.create_index("ix_job_sync_signatures_location_target", "job_sync_signatures", ["job_location_target_id"])
    op.create_index("ix_job_sync_signatures_location_mapping", "job_sync_signatures", ["job_provider_location_mapping_id"])
    op.create_index("ix_job_sync_signatures_status_enabled", "job_sync_signatures", ["verification_status", "enabled"])

    with op.batch_alter_table("job_sync_runs") as batch_op:
        batch_op.add_column(sa.Column("job_sync_signature_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_job_sync_runs_job_sync_signature_id",
            "job_sync_signatures",
            ["job_sync_signature_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_job_sync_runs_signature", ["job_sync_signature_id"])


def downgrade() -> None:
    existing_indexes = set()
    existing_foreign_keys = set()
    if not context.is_offline_mode():
        bind = op.get_bind()
        existing_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("job_sync_runs")}
        existing_foreign_keys = {fk["name"] for fk in sa.inspect(bind).get_foreign_keys("job_sync_runs")}
    with op.batch_alter_table("job_sync_runs") as batch_op:
        if context.is_offline_mode() or "ix_job_sync_runs_signature" in existing_indexes:
            batch_op.drop_index("ix_job_sync_runs_signature")
        if context.is_offline_mode() or "fk_job_sync_runs_job_sync_signature_id" in existing_foreign_keys:
            batch_op.drop_constraint("fk_job_sync_runs_job_sync_signature_id", type_="foreignkey")
        batch_op.drop_column("job_sync_signature_id")

    op.drop_index("ix_job_sync_signatures_status_enabled", table_name="job_sync_signatures")
    op.drop_index("ix_job_sync_signatures_location_mapping", table_name="job_sync_signatures")
    op.drop_index("ix_job_sync_signatures_location_target", table_name="job_sync_signatures")
    op.drop_index("ix_job_sync_signatures_provider_request", table_name="job_sync_signatures")
    op.drop_index("ix_job_sync_signatures_provider_completed", table_name="job_sync_signatures")
    op.drop_index("ix_job_sync_signatures_provider_enabled", table_name="job_sync_signatures")
    op.drop_table("job_sync_signatures")
