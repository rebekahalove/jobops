"""Add canonical companies and profile company links.

Revision ID: 20260529_0017
Revises: 20260528_0016
Create Date: 2026-05-29
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
import uuid
from urllib.parse import urlparse

import sqlalchemy as sa
from alembic import op


revision: str = "20260529_0017"
down_revision: str | None = "20260528_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("normalized_name", sa.String(length=240), nullable=True),
        sa.Column("domain", sa.String(length=255), nullable=True),
        sa.Column("normalized_domain", sa.String(length=255), nullable=True),
        sa.Column("website_url", sa.Text(), nullable=True),
        sa.Column("careers_url", sa.Text(), nullable=True),
        sa.Column("job_listings_url", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("headquarters_city", sa.String(length=160), nullable=True),
        sa.Column("headquarters_country", sa.String(length=160), nullable=True),
        sa.Column("operating_countries", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("hiring_locations", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("remote_policy", sa.String(length=40), nullable=False, server_default="unknown"),
        sa.Column("source_urls", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("source_summary", sa.Text(), nullable=True),
        sa.Column("data_confidence", sa.String(length=40), nullable=False, server_default="medium"),
        sa.Column("greenhouse_board_token", sa.String(length=240), nullable=True),
        sa.Column("ashby_board_url", sa.Text(), nullable=True),
        sa.Column("lever_slug", sa.String(length=240), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("normalized_domain", name="uq_companies_normalized_domain"),
    )
    op.create_index("ix_companies_normalized_name", "companies", ["normalized_name"])
    op.create_index("ix_companies_last_seen", "companies", ["last_seen_at"])

    op.create_table(
        "candidate_companies",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("candidate_profile_id", sa.String(length=36), sa.ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("company_id", sa.String(length=36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("review_status", sa.String(length=40), nullable=False, server_default="new"),
        sa.Column("derivation_status", sa.String(length=40), nullable=False, server_default="model_derived"),
        sa.Column("fit_reason", sa.Text(), nullable=True),
        sa.Column("role_fit_tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("mission_fit_tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("discovery_query", sa.Text(), nullable=True),
        sa.Column("search_queries_used", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("provider_grounding_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("discovered_by", sa.String(length=120), nullable=True),
        sa.Column("personal_source_urls", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("candidate_profile_id", "company_id", name="uq_candidate_companies_profile_company"),
    )
    op.create_index("ix_candidate_companies_profile_added", "candidate_companies", ["candidate_profile_id", "added_at"])
    op.create_index("ix_candidate_companies_profile_review_added", "candidate_companies", ["candidate_profile_id", "review_status", "added_at"])

    with op.batch_alter_table("job_roles") as batch_op:
        batch_op.add_column(sa.Column("company_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key("fk_job_roles_company_id_companies", "companies", ["company_id"], ["id"], ondelete="SET NULL")
    with op.batch_alter_table("applications") as batch_op:
        batch_op.add_column(sa.Column("company_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key("fk_applications_company_id_companies", "companies", ["company_id"], ["id"], ondelete="SET NULL")

    target_company_map = _backfill_target_companies()
    _backfill_company_references(target_company_map)

    op.drop_index("ix_job_roles_company_title", table_name="job_roles")
    op.create_index("ix_job_roles_company_title", "job_roles", ["company_id", "title"])
    with op.batch_alter_table("applications") as batch_op:
        batch_op.drop_column("target_company_id")
    with op.batch_alter_table("job_roles") as batch_op:
        batch_op.drop_column("target_company_id")
    op.drop_index("ix_target_companies_profile_review_created", table_name="target_companies")
    op.drop_index("ix_target_companies_profile_created", table_name="target_companies")
    op.drop_index("ix_target_companies_profile_normalized_name", table_name="target_companies")
    op.drop_index("ix_target_companies_profile_name", table_name="target_companies")
    op.drop_table("target_companies")


def downgrade() -> None:
    _recreate_target_companies()
    _backfill_legacy_target_companies()
    with op.batch_alter_table("job_roles") as batch_op:
        batch_op.add_column(sa.Column("target_company_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_job_roles_target_company_id_target_companies",
            "target_companies",
            ["target_company_id"],
            ["id"],
            ondelete="SET NULL",
        )
    with op.batch_alter_table("applications") as batch_op:
        batch_op.add_column(sa.Column("target_company_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_applications_target_company_id_target_companies",
            "target_companies",
            ["target_company_id"],
            ["id"],
            ondelete="SET NULL",
        )
    _backfill_legacy_company_references()
    op.drop_index("ix_job_roles_company_title", table_name="job_roles")
    op.create_index("ix_job_roles_company_title", "job_roles", ["target_company_id", "title"])
    with op.batch_alter_table("applications") as batch_op:
        batch_op.drop_column("company_id")
    with op.batch_alter_table("job_roles") as batch_op:
        batch_op.drop_column("company_id")
    op.drop_index("ix_candidate_companies_profile_review_added", table_name="candidate_companies")
    op.drop_index("ix_candidate_companies_profile_added", table_name="candidate_companies")
    op.drop_table("candidate_companies")
    op.drop_index("ix_companies_last_seen", table_name="companies")
    op.drop_index("ix_companies_normalized_name", table_name="companies")
    op.drop_table("companies")


def _backfill_target_companies() -> dict[str, str]:
    bind = op.get_bind()
    metadata = sa.MetaData()
    target_companies = sa.Table("target_companies", metadata, autoload_with=bind)
    companies = sa.Table("companies", metadata, autoload_with=bind)
    candidate_companies = sa.Table("candidate_companies", metadata, autoload_with=bind)

    company_by_domain: dict[str, str] = {}
    company_by_domainless_name: dict[str, str] = {}
    link_keys: set[tuple[str, str]] = set()
    target_company_map: dict[str, str] = {}

    rows = list(bind.execute(sa.select(target_companies).order_by(target_companies.c.created_at.asc())).mappings())
    for row in rows:
        normalized_name = normalize_company_name(row.get("normalized_name") or row.get("name"))
        source_urls = coerce_list(row.get("source_urls"))
        normalized_domain = first_domain(
            row.get("website_url"),
            row.get("careers_url"),
            row.get("job_listings_url"),
            *source_urls,
        )

        company_id = None
        if normalized_domain:
            company_id = company_by_domain.get(normalized_domain)
            if company_id is None:
                company_id = bind.scalar(sa.select(companies.c.id).where(companies.c.normalized_domain == normalized_domain))
        if company_id is None and normalized_name:
            company_id = company_by_domainless_name.get(normalized_name)
            if company_id is None:
                company_id = bind.scalar(
                    sa.select(companies.c.id).where(
                        companies.c.normalized_name == normalized_name,
                        companies.c.normalized_domain.is_(None),
                    )
                )

        timestamp = row.get("created_at") or datetime.now(timezone.utc)
        last_seen_at = row.get("last_checked_at") or row.get("updated_at") or timestamp
        if company_id is None:
            company_id = str(uuid.uuid4())
            bind.execute(
                companies.insert().values(
                    id=company_id,
                    name=row.get("name"),
                    normalized_name=normalized_name or None,
                    domain=normalized_domain,
                    normalized_domain=normalized_domain,
                    website_url=row.get("website_url"),
                    careers_url=row.get("careers_url"),
                    job_listings_url=row.get("job_listings_url"),
                    description=row.get("description"),
                    headquarters_city=row.get("headquarters_city"),
                    headquarters_country=row.get("headquarters_country"),
                    operating_countries=coerce_list(row.get("operating_countries")),
                    hiring_locations=coerce_list(row.get("hiring_locations")),
                    remote_policy=row.get("remote_policy") or "unknown",
                    source_urls=source_urls,
                    source_summary=row.get("source_summary"),
                    data_confidence="medium",
                    first_seen_at=timestamp,
                    last_seen_at=last_seen_at,
                    created_at=timestamp,
                    updated_at=row.get("updated_at") or timestamp,
                )
            )
        else:
            existing = bind.execute(sa.select(companies).where(companies.c.id == company_id)).mappings().first()
            if existing is not None:
                bind.execute(
                    companies.update()
                    .where(companies.c.id == company_id)
                    .values(
                        website_url=existing.get("website_url") or row.get("website_url"),
                        careers_url=existing.get("careers_url") or row.get("careers_url"),
                        job_listings_url=existing.get("job_listings_url") or row.get("job_listings_url"),
                        description=existing.get("description") or row.get("description"),
                        headquarters_city=existing.get("headquarters_city") or row.get("headquarters_city"),
                        headquarters_country=existing.get("headquarters_country") or row.get("headquarters_country"),
                        operating_countries=merge_lists(coerce_list(existing.get("operating_countries")), coerce_list(row.get("operating_countries"))),
                        hiring_locations=merge_lists(coerce_list(existing.get("hiring_locations")), coerce_list(row.get("hiring_locations"))),
                        source_urls=merge_lists(coerce_list(existing.get("source_urls")), source_urls),
                        source_summary=existing.get("source_summary") or row.get("source_summary"),
                        last_seen_at=last_seen_at,
                        updated_at=row.get("updated_at") or last_seen_at,
                    )
                )

        if normalized_domain:
            company_by_domain[normalized_domain] = company_id
        elif normalized_name:
            company_by_domainless_name[normalized_name] = company_id
        target_company_map[row.get("id")] = company_id

        link_key = (row.get("candidate_profile_id"), company_id)
        if link_key in link_keys:
            continue
        existing_link = bind.scalar(
            sa.select(candidate_companies.c.id).where(
                candidate_companies.c.candidate_profile_id == row.get("candidate_profile_id"),
                candidate_companies.c.company_id == company_id,
            )
        )
        if existing_link is not None:
            link_keys.add(link_key)
            continue

        bind.execute(
            candidate_companies.insert().values(
                id=str(uuid.uuid4()),
                candidate_profile_id=row.get("candidate_profile_id"),
                company_id=company_id,
                review_status=row.get("review_status") or "new",
                derivation_status=row.get("derivation_status") or "model_derived",
                fit_reason=row.get("fit_reason"),
                role_fit_tags=coerce_list(row.get("role_fit_tags")),
                mission_fit_tags=coerce_list(row.get("mission_fit_tags")),
                notes=row.get("notes") or "",
                discovery_query=row.get("discovery_query"),
                search_queries_used=coerce_list(row.get("search_queries_used")),
                provider_grounding_metadata=row.get("provider_grounding_metadata") or {},
                discovered_by=row.get("discovered_by"),
                personal_source_urls=[],
                added_at=timestamp,
                last_checked_at=row.get("last_checked_at"),
                created_at=timestamp,
                updated_at=row.get("updated_at") or timestamp,
            )
        )
        link_keys.add(link_key)
    return target_company_map


def _backfill_company_references(target_company_map: dict[str, str]) -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    job_roles = sa.Table("job_roles", metadata, autoload_with=bind)
    applications = sa.Table("applications", metadata, autoload_with=bind)
    for target_company_id, company_id in target_company_map.items():
        bind.execute(
            job_roles.update()
            .where(job_roles.c.target_company_id == target_company_id)
            .values(company_id=company_id)
        )
        bind.execute(
            applications.update()
            .where(applications.c.target_company_id == target_company_id)
            .values(company_id=company_id)
        )


def _recreate_target_companies() -> None:
    op.create_table(
        "target_companies",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("candidate_profile_id", sa.String(length=36), sa.ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("normalized_name", sa.String(length=240), nullable=True),
        sa.Column("website_url", sa.Text(), nullable=True),
        sa.Column("careers_url", sa.Text(), nullable=True),
        sa.Column("job_listings_url", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("headquarters_city", sa.String(length=160), nullable=True),
        sa.Column("headquarters_country", sa.String(length=160), nullable=True),
        sa.Column("operating_countries", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("hiring_locations", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("remote_policy", sa.String(length=40), nullable=False, server_default="unknown"),
        sa.Column("role_fit_tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("mission_fit_tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("fit_reason", sa.Text(), nullable=True),
        sa.Column("source_urls", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("source_summary", sa.Text(), nullable=True),
        sa.Column("discovery_query", sa.Text(), nullable=True),
        sa.Column("search_queries_used", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("provider_grounding_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("discovered_by", sa.String(length=120), nullable=True),
        sa.Column("derivation_status", sa.String(length=40), nullable=False, server_default="user_entered"),
        sa.Column("review_status", sa.String(length=40), nullable=False, server_default="reviewed"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("candidate_profile_id", "name", name="uq_target_companies_profile_name"),
    )
    op.create_index("ix_target_companies_profile_name", "target_companies", ["candidate_profile_id", "name"])
    op.create_index("ix_target_companies_profile_normalized_name", "target_companies", ["candidate_profile_id", "normalized_name"])
    op.create_index("ix_target_companies_profile_created", "target_companies", ["candidate_profile_id", "created_at"])
    op.create_index("ix_target_companies_profile_review_created", "target_companies", ["candidate_profile_id", "review_status", "created_at"])


def _backfill_legacy_target_companies() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    companies = sa.Table("companies", metadata, autoload_with=bind)
    candidate_companies = sa.Table("candidate_companies", metadata, autoload_with=bind)
    target_companies = sa.Table("target_companies", metadata, autoload_with=bind)
    rows = bind.execute(
        sa.select(
            candidate_companies.c.id.label("link_id"),
            candidate_companies.c.candidate_profile_id,
            candidate_companies.c.review_status,
            candidate_companies.c.derivation_status,
            candidate_companies.c.fit_reason,
            candidate_companies.c.role_fit_tags,
            candidate_companies.c.mission_fit_tags,
            candidate_companies.c.notes,
            candidate_companies.c.discovery_query,
            candidate_companies.c.search_queries_used,
            candidate_companies.c.provider_grounding_metadata,
            candidate_companies.c.discovered_by,
            candidate_companies.c.last_checked_at,
            candidate_companies.c.created_at,
            candidate_companies.c.updated_at,
            companies.c.name,
            companies.c.normalized_name,
            companies.c.website_url,
            companies.c.careers_url,
            companies.c.job_listings_url,
            companies.c.description,
            companies.c.headquarters_city,
            companies.c.headquarters_country,
            companies.c.operating_countries,
            companies.c.hiring_locations,
            companies.c.remote_policy,
            companies.c.source_urls,
            companies.c.source_summary,
        ).join(companies, companies.c.id == candidate_companies.c.company_id)
    ).mappings()
    for row in rows:
        bind.execute(
            target_companies.insert().values(
                id=row["link_id"],
                candidate_profile_id=row["candidate_profile_id"],
                name=row["name"],
                normalized_name=row["normalized_name"],
                website_url=row["website_url"],
                careers_url=row["careers_url"],
                job_listings_url=row["job_listings_url"],
                description=row["description"],
                headquarters_city=row["headquarters_city"],
                headquarters_country=row["headquarters_country"],
                operating_countries=coerce_list(row["operating_countries"]),
                hiring_locations=coerce_list(row["hiring_locations"]),
                remote_policy=row["remote_policy"] or "unknown",
                role_fit_tags=coerce_list(row["role_fit_tags"]),
                mission_fit_tags=coerce_list(row["mission_fit_tags"]),
                fit_reason=row["fit_reason"],
                source_urls=coerce_list(row["source_urls"]),
                source_summary=row["source_summary"],
                discovery_query=row["discovery_query"],
                search_queries_used=coerce_list(row["search_queries_used"]),
                provider_grounding_metadata=row["provider_grounding_metadata"] or {},
                discovered_by=row["discovered_by"],
                derivation_status=row["derivation_status"] or "model_derived",
                review_status=row["review_status"] or "new",
                notes=row["notes"] or "",
                last_checked_at=row["last_checked_at"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
        )


def _backfill_legacy_company_references() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    candidate_companies = sa.Table("candidate_companies", metadata, autoload_with=bind)
    job_roles = sa.Table("job_roles", metadata, autoload_with=bind)
    applications = sa.Table("applications", metadata, autoload_with=bind)
    links = list(bind.execute(sa.select(candidate_companies)).mappings())
    for link in links:
        bind.execute(
            job_roles.update()
            .where(
                job_roles.c.candidate_profile_id == link["candidate_profile_id"],
                job_roles.c.company_id == link["company_id"],
            )
            .values(target_company_id=link["id"])
        )
        bind.execute(
            applications.update()
            .where(
                applications.c.candidate_profile_id == link["candidate_profile_id"],
                applications.c.company_id == link["company_id"],
            )
            .values(target_company_id=link["id"])
        )


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


def merge_lists(existing: list[str], incoming: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for value in [*existing, *incoming]:
        key = value.casefold()
        if key not in seen:
            merged.append(value)
            seen.add(key)
    return merged[:12]
