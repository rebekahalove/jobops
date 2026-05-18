"""Extend target companies for company discovery.

Revision ID: 20260518_0005
Revises: 20260518_0004
Create Date: 2026-05-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260518_0005"
down_revision: str | None = "20260518_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("target_companies") as batch_op:
        batch_op.add_column(sa.Column("normalized_name", sa.String(length=240), nullable=True))
        batch_op.add_column(sa.Column("careers_url", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("job_listings_url", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("description", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("headquarters_city", sa.String(length=160), nullable=True))
        batch_op.add_column(sa.Column("headquarters_country", sa.String(length=160), nullable=True))
        batch_op.add_column(sa.Column("operating_countries", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch_op.add_column(sa.Column("hiring_locations", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch_op.add_column(sa.Column("remote_policy", sa.String(length=40), nullable=False, server_default="unknown"))
        batch_op.add_column(sa.Column("role_fit_tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch_op.add_column(sa.Column("mission_fit_tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch_op.add_column(sa.Column("fit_reason", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("source_urls", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch_op.add_column(sa.Column("source_summary", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("discovery_query", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("search_queries_used", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        batch_op.add_column(sa.Column("provider_grounding_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
        batch_op.add_column(sa.Column("discovered_by", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("derivation_status", sa.String(length=40), nullable=False, server_default="user_entered"))
        batch_op.add_column(sa.Column("review_status", sa.String(length=40), nullable=False, server_default="reviewed"))
        batch_op.add_column(sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True))

    op.execute("UPDATE target_companies SET normalized_name = lower(trim(name)) WHERE normalized_name IS NULL")
    op.create_index(
        "ix_target_companies_profile_normalized_name",
        "target_companies",
        ["candidate_profile_id", "normalized_name"],
    )


def downgrade() -> None:
    op.drop_index("ix_target_companies_profile_normalized_name", table_name="target_companies")
    with op.batch_alter_table("target_companies") as batch_op:
        batch_op.drop_column("last_checked_at")
        batch_op.drop_column("review_status")
        batch_op.drop_column("derivation_status")
        batch_op.drop_column("discovered_by")
        batch_op.drop_column("provider_grounding_metadata")
        batch_op.drop_column("search_queries_used")
        batch_op.drop_column("discovery_query")
        batch_op.drop_column("source_summary")
        batch_op.drop_column("source_urls")
        batch_op.drop_column("fit_reason")
        batch_op.drop_column("mission_fit_tags")
        batch_op.drop_column("role_fit_tags")
        batch_op.drop_column("remote_policy")
        batch_op.drop_column("hiring_locations")
        batch_op.drop_column("operating_countries")
        batch_op.drop_column("headquarters_country")
        batch_op.drop_column("headquarters_city")
        batch_op.drop_column("description")
        batch_op.drop_column("job_listings_url")
        batch_op.drop_column("careers_url")
        batch_op.drop_column("normalized_name")
