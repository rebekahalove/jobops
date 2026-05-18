"""Add explicit experience project date and location fields.

Revision ID: 20260518_0004
Revises: 20260513_0003
Create Date: 2026-05-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260518_0004"
down_revision: str | None = "20260513_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("experience_project_drafts") as batch_op:
        batch_op.add_column(sa.Column("start_date", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("end_date", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("location", sa.String(length=160), nullable=True))

    bind = op.get_bind()
    dialect_name = bind.dialect.name
    if dialect_name == "sqlite":
        op.execute(
            """
            UPDATE experience_project_drafts
            SET
              start_date = json_extract(structured_value, '$.startDate'),
              end_date = json_extract(structured_value, '$.endDate'),
              location = json_extract(structured_value, '$.location')
            WHERE structured_value IS NOT NULL
            """
        )
    elif dialect_name == "postgresql":
        op.execute(
            """
            UPDATE experience_project_drafts
            SET
              start_date = structured_value ->> 'startDate',
              end_date = structured_value ->> 'endDate',
              location = structured_value ->> 'location'
            WHERE structured_value IS NOT NULL
            """
        )


def downgrade() -> None:
    with op.batch_alter_table("experience_project_drafts") as batch_op:
        batch_op.drop_column("location")
        batch_op.drop_column("end_date")
        batch_op.drop_column("start_date")
