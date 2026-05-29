from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db.models import CandidateCompany, Company


CANONICAL_COMPANY_URL_FIELDS = {"website_url", "careers_url", "job_listings_url", "source_urls"}


@dataclass(frozen=True)
class CompanyProfileLinkResult:
    company: Company
    link: CandidateCompany
    created_link: bool


def normalize_company_name(value: str | None) -> str:
    return " ".join((value or "").split()).casefold()


def domain_from_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value if "://" in value else f"https://{value}")
    hostname = (parsed.hostname or "").casefold()
    return hostname.removeprefix("www.") or None


def normalized_domain_from_company_urls(*values: str | None, source_urls: list[str] | None = None) -> str | None:
    for value in [*values, *(source_urls or [])]:
        domain = domain_from_url(value)
        if domain:
            return domain
    return None


def clean_company_source_urls(values: list[str | None]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value:
            continue
        stripped = value.strip()
        key = stripped.casefold()
        if stripped and key not in seen:
            cleaned.append(stripped)
            seen.add(key)
    return cleaned


def find_canonical_company(
    session: Session,
    *,
    normalized_name: str | None,
    normalized_domain: str | None,
) -> Company | None:
    if normalized_domain:
        by_domain = session.scalar(select(Company).where(Company.normalized_domain == normalized_domain))
        if by_domain is not None:
            return by_domain

    if normalized_name:
        statement = select(Company).where(Company.normalized_name == normalized_name)
        if normalized_domain:
            statement = statement.where(Company.normalized_domain.is_(None))
        matches = list(session.scalars(statement.limit(2)))
        if len(matches) == 1:
            return matches[0]

    return None


def upsert_canonical_company(
    session: Session,
    *,
    name: str,
    normalized_name: str | None = None,
    website_url: str | None = None,
    careers_url: str | None = None,
    job_listings_url: str | None = None,
    description: str | None = None,
    headquarters_city: str | None = None,
    headquarters_country: str | None = None,
    operating_countries: list[str] | None = None,
    hiring_locations: list[str] | None = None,
    remote_policy: str | None = None,
    source_urls: list[str] | None = None,
    source_summary: str | None = None,
    data_confidence: str | None = None,
    greenhouse_board_token: str | None = None,
    ashby_board_url: str | None = None,
    lever_slug: str | None = None,
    last_seen_at: datetime | None = None,
) -> Company:
    cleaned_name = name.strip()
    if not cleaned_name:
        raise ValueError("Company name is required.")

    clean_sources = clean_company_source_urls(source_urls or [])
    clean_normalized_name = normalize_company_name(normalized_name or cleaned_name) or None
    normalized_domain = normalized_domain_from_company_urls(
        website_url,
        careers_url,
        job_listings_url,
        ashby_board_url,
        source_urls=clean_sources,
    )
    now = last_seen_at or datetime.now(timezone.utc)
    company = find_canonical_company(
        session,
        normalized_name=clean_normalized_name,
        normalized_domain=normalized_domain,
    )

    if company is None:
        company = Company(
            name=cleaned_name,
            normalized_name=clean_normalized_name,
            domain=normalized_domain,
            normalized_domain=normalized_domain,
            website_url=website_url,
            careers_url=careers_url,
            job_listings_url=job_listings_url,
            description=description,
            headquarters_city=headquarters_city,
            headquarters_country=headquarters_country,
            operating_countries=operating_countries or [],
            hiring_locations=hiring_locations or [],
            remote_policy=remote_policy or "unknown",
            source_urls=clean_sources[:12],
            source_summary=source_summary,
            data_confidence=data_confidence or "medium",
            greenhouse_board_token=greenhouse_board_token,
            ashby_board_url=ashby_board_url,
            lever_slug=lever_slug,
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(company)
        session.flush()
        return company

    company.normalized_name = company.normalized_name or clean_normalized_name
    if normalized_domain and not company.normalized_domain:
        company.domain = company.domain or normalized_domain
        company.normalized_domain = normalized_domain
    company.website_url = company.website_url or website_url
    company.careers_url = company.careers_url or careers_url
    company.job_listings_url = company.job_listings_url or job_listings_url
    company.description = company.description or description
    company.headquarters_city = company.headquarters_city or headquarters_city
    company.headquarters_country = company.headquarters_country or headquarters_country
    company.operating_countries = merge_text_lists(company.operating_countries or [], operating_countries or [], limit=12)
    company.hiring_locations = merge_text_lists(company.hiring_locations or [], hiring_locations or [], limit=16)
    company.remote_policy = company.remote_policy if company.remote_policy != "unknown" else (remote_policy or "unknown")
    company.source_urls = merge_text_lists(company.source_urls or [], clean_sources, limit=12)
    company.source_summary = company.source_summary or source_summary
    company.data_confidence = company.data_confidence or data_confidence or "medium"
    company.greenhouse_board_token = company.greenhouse_board_token or greenhouse_board_token
    company.ashby_board_url = company.ashby_board_url or ashby_board_url
    company.lever_slug = company.lever_slug or lever_slug
    company.last_seen_at = now
    session.add(company)
    session.flush()
    return company


def ensure_candidate_company_link(
    session: Session,
    *,
    candidate_profile_id: str,
    company: Company,
    review_status: str = "new",
    derivation_status: str = "model_derived",
    fit_reason: str | None = None,
    role_fit_tags: list[str] | None = None,
    mission_fit_tags: list[str] | None = None,
    notes: str | None = None,
    discovery_query: str | None = None,
    search_queries_used: list[str] | None = None,
    provider_grounding_metadata: dict[str, Any] | None = None,
    discovered_by: str | None = None,
    personal_source_urls: list[str] | None = None,
    now: datetime | None = None,
) -> CompanyProfileLinkResult:
    timestamp = now or datetime.now(timezone.utc)
    link = session.scalar(
        select(CandidateCompany).where(
            CandidateCompany.candidate_profile_id == candidate_profile_id,
            CandidateCompany.company_id == company.id,
        )
    )
    created = link is None
    if link is None:
        link = CandidateCompany(
            candidate_profile_id=candidate_profile_id,
            company_id=company.id,
            review_status=review_status,
            derivation_status=derivation_status,
            fit_reason=fit_reason,
            role_fit_tags=role_fit_tags or [],
            mission_fit_tags=mission_fit_tags or [],
            notes=notes or "",
            discovery_query=discovery_query,
            search_queries_used=search_queries_used or [],
            provider_grounding_metadata=provider_grounding_metadata or {},
            discovered_by=discovered_by,
            personal_source_urls=personal_source_urls or [],
            added_at=timestamp,
            last_checked_at=timestamp,
        )
        session.add(link)
    else:
        link.fit_reason = fit_reason or link.fit_reason
        link.role_fit_tags = merge_text_lists(link.role_fit_tags or [], role_fit_tags or [], limit=12)
        link.mission_fit_tags = merge_text_lists(link.mission_fit_tags or [], mission_fit_tags or [], limit=12)
        if notes and not link.notes:
            link.notes = notes
        link.discovery_query = discovery_query or link.discovery_query
        link.search_queries_used = merge_text_lists(link.search_queries_used or [], search_queries_used or [], limit=12)
        link.provider_grounding_metadata = provider_grounding_metadata or link.provider_grounding_metadata or {}
        link.discovered_by = discovered_by or link.discovered_by
        link.personal_source_urls = merge_text_lists(link.personal_source_urls or [], personal_source_urls or [], limit=12)
        link.last_checked_at = timestamp
        session.add(link)

    session.flush()
    return CompanyProfileLinkResult(company=company, link=link, created_link=created)


def merge_text_lists(existing: list[str], incoming: list[str], *, limit: int) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for value in [*existing, *incoming]:
        if not isinstance(value, str):
            continue
        stripped = value.strip()
        key = stripped.casefold()
        if stripped and key not in seen:
            merged.append(stripped)
            seen.add(key)
        if len(merged) >= limit:
            break
    return merged
