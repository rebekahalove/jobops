"""Add source application field summaries.

Revision ID: 20260613_0033
Revises: 20260612_0032
Create Date: 2026-06-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op


revision: str = "20260613_0033"
down_revision: str | None = "20260612_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


APPLICATION_FIELD_COLUMNS = (
    "application_fields_json",
    "application_requirements_json",
    "pay_transparency_json",
)


def upgrade() -> None:
    existing_columns = set()
    if not context.is_offline_mode():
        existing_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("job_listing_sources")}
    with op.batch_alter_table("job_listing_sources") as batch_op:
        for column_name in APPLICATION_FIELD_COLUMNS:
            if context.is_offline_mode() or column_name not in existing_columns:
                batch_op.add_column(sa.Column(column_name, sa.JSON(), nullable=True))


def downgrade() -> None:
    existing_columns = set()
    if not context.is_offline_mode():
        bind = op.get_bind()
        existing_columns = {column["name"] for column in sa.inspect(bind).get_columns("job_listing_sources")}
        populated_conditions = [
            f"{column_name} IS NOT NULL" for column_name in APPLICATION_FIELD_COLUMNS if column_name in existing_columns
        ]
        if populated_conditions:
            populated_count = bind.execute(
                sa.text(f"SELECT count(*) FROM job_listing_sources WHERE {' OR '.join(populated_conditions)}")
            ).scalar()
            if populated_count:
                return
    with op.batch_alter_table("job_listing_sources") as batch_op:
        for column_name in reversed(APPLICATION_FIELD_COLUMNS):
            if context.is_offline_mode() or column_name in existing_columns:
                batch_op.drop_column(column_name)
