"""Link synced job listings to normalized location targets.

Revision ID: 20260610_0029
Revises: 20260610_0028
Create Date: 2026-06-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op


revision: str = "20260610_0029"
down_revision: str | None = "20260610_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("job_listings") as batch_op:
        batch_op.add_column(sa.Column("job_location_target_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_job_listings_job_location_target_id",
            "job_location_targets",
            ["job_location_target_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_job_listings_location_target_active",
            ["job_location_target_id", "is_active"],
        )


def downgrade() -> None:
    existing_indexes = set()
    existing_foreign_keys = set()
    if not context.is_offline_mode():
        bind = op.get_bind()
        existing_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("job_listings")}
        existing_foreign_keys = {fk["name"] for fk in sa.inspect(bind).get_foreign_keys("job_listings")}
    with op.batch_alter_table("job_listings") as batch_op:
        if context.is_offline_mode() or "ix_job_listings_location_target_active" in existing_indexes:
            batch_op.drop_index("ix_job_listings_location_target_active")
        if context.is_offline_mode() or "fk_job_listings_job_location_target_id" in existing_foreign_keys:
            batch_op.drop_constraint("fk_job_listings_job_location_target_id", type_="foreignkey")
        batch_op.drop_column("job_location_target_id")
