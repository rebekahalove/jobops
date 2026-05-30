"""Drop legacy target companies if an early 0017 migration created canonical tables.

Revision ID: 20260529_0018
Revises: 20260529_0017
Create Date: 2026-05-29
"""

from __future__ import annotations

from collections.abc import Sequence
from urllib.parse import urlparse

import sqlalchemy as sa
from alembic import op
from alembic import context


revision: str = "20260529_0018"
down_revision: str | None = "20260529_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if context.is_offline_mode():
        op.execute("-- Skipping legacy target_companies compatibility cleanup in offline SQL generation.")
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "target_companies" not in tables:
        return

    job_role_columns = {column["name"] for column in inspector.get_columns("job_roles")}
    application_columns = {column["name"] for column in inspector.get_columns("applications")}
    if "company_id" not in job_role_columns:
        with op.batch_alter_table("job_roles") as batch_op:
            batch_op.add_column(sa.Column("company_id", sa.String(length=36), nullable=True))
            batch_op.create_foreign_key("fk_job_roles_company_id_companies", "companies", ["company_id"], ["id"], ondelete="SET NULL")
    if "company_id" not in application_columns:
        with op.batch_alter_table("applications") as batch_op:
            batch_op.add_column(sa.Column("company_id", sa.String(length=36), nullable=True))
            batch_op.create_foreign_key("fk_applications_company_id_companies", "companies", ["company_id"], ["id"], ondelete="SET NULL")

    _backfill_company_references()

    indexes = {index["name"] for index in inspector.get_indexes("job_roles")}
    if "ix_job_roles_company_title" in indexes:
        op.drop_index("ix_job_roles_company_title", table_name="job_roles")
    op.create_index("ix_job_roles_company_title", "job_roles", ["company_id", "title"])

    if "target_company_id" in application_columns:
        with op.batch_alter_table("applications") as batch_op:
            batch_op.drop_column("target_company_id")
    if "target_company_id" in job_role_columns:
        with op.batch_alter_table("job_roles") as batch_op:
            batch_op.drop_column("target_company_id")

    target_indexes = {index["name"] for index in inspector.get_indexes("target_companies")}
    for index_name in (
        "ix_target_companies_profile_review_created",
        "ix_target_companies_profile_created",
        "ix_target_companies_profile_normalized_name",
        "ix_target_companies_profile_name",
    ):
        if index_name in target_indexes:
            op.drop_index(index_name, table_name="target_companies")
    op.drop_table("target_companies")


def downgrade() -> None:
    # Revision 0017 downgrade recreates target_companies when rolling back before the canonical-company branch.
    pass


def _backfill_company_references() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    target_companies = sa.Table("target_companies", metadata, autoload_with=bind)
    companies = sa.Table("companies", metadata, autoload_with=bind)
    candidate_companies = sa.Table("candidate_companies", metadata, autoload_with=bind)
    job_roles = sa.Table("job_roles", metadata, autoload_with=bind)
    applications = sa.Table("applications", metadata, autoload_with=bind)

    for target in bind.execute(sa.select(target_companies)).mappings():
        company_id = _find_company_id(bind, companies, candidate_companies, target)
        if company_id is None:
            continue
        bind.execute(
            job_roles.update()
            .where(job_roles.c.target_company_id == target["id"])
            .values(company_id=company_id)
        )
        bind.execute(
            applications.update()
            .where(applications.c.target_company_id == target["id"])
            .values(company_id=company_id)
        )


def _find_company_id(bind, companies: sa.Table, candidate_companies: sa.Table, target) -> str | None:
    normalized_domain = first_domain(
        target.get("website_url"),
        target.get("careers_url"),
        target.get("job_listings_url"),
        *coerce_list(target.get("source_urls")),
    )
    statement = (
        sa.select(candidate_companies.c.company_id)
        .join(companies, companies.c.id == candidate_companies.c.company_id)
        .where(candidate_companies.c.candidate_profile_id == target["candidate_profile_id"])
    )
    if normalized_domain:
        match = bind.scalar(statement.where(companies.c.normalized_domain == normalized_domain))
        if match is not None:
            return match
    normalized_name = normalize_company_name(target.get("normalized_name") or target.get("name"))
    if normalized_name:
        match = bind.scalar(statement.where(companies.c.normalized_name == normalized_name))
        if match is not None:
            return match
    return None


def normalize_company_name(value: str | None) -> str:
    return " ".join((value or "").split()).casefold()


def first_domain(*values: str | None) -> str | None:
    for value in values:
        if not value:
            continue
        parsed = urlparse(value if "://" in value else f"https://{value}")
        hostname = (parsed.hostname or "").casefold()
        if hostname:
            return hostname.removeprefix("www.")
    return None


def coerce_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item.strip()]
    return []
