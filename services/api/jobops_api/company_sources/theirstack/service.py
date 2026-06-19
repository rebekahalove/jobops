from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...company_canonicalization import ensure_candidate_company_link, find_canonical_company, upsert_canonical_company
from ...db.models import Company, CompanySource
from ...job_discovery.greenhouse_utils import canonical_greenhouse_jobs_api_url
from ...settings import Settings
from .client import TheirStackCompanySearchClient, TheirStackCompanySearchError
from .models import (
    NormalizedCompanyEnrichment,
    TheirStackCompanyEnrichmentResult,
    TheirStackCompanySearchDiagnostics,
    TheirStackCompanySearchRequest,
)
from .normalizer import normalize_theirstack_company


class TheirStackCompanyEnrichmentService:
    def __init__(
        self,
        *,
        session: Session,
        settings: Settings,
        client: TheirStackCompanySearchClient | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.client = client

    def search_and_upsert_companies(
        self,
        request: TheirStackCompanySearchRequest,
        *,
        candidate_profile_id: str | None = None,
        link_to_profile: bool = False,
        discovery_query: str | None = None,
    ) -> TheirStackCompanyEnrichmentResult:
        if not self.settings.theirstack_company_search_enabled or not self.settings.theirstack_api_key:
            requested_pages = request.max_pages or self.settings.theirstack_company_search_max_pages
            effective_request = request_with_settings_defaults(request, settings=self.settings)
            diagnostics = TheirStackCompanySearchDiagnostics(
                enabled=False,
                requested_pages=max(1, requested_pages),
                skipped_pages=max(1, requested_pages),
                request_shape=effective_request.sanitized_shape(),
                error_type="theirstack_unavailable",
                error_message="TheirStack company search is disabled or missing an API key.",
            ).to_dict()
            return TheirStackCompanyEnrichmentResult(
                status="unavailable",
                diagnostics=diagnostics,
                error_message="TheirStack company search is disabled or missing an API key.",
            )

        client = self.client or TheirStackCompanySearchClient(
            api_key=self.settings.theirstack_api_key,
            timeout_seconds=self.settings.llm_request_timeout_seconds,
        )
        effective_request = request_with_settings_defaults(request, settings=self.settings)
        try:
            search_result = client.search_companies(effective_request)
        except TheirStackCompanySearchError as exc:
            return TheirStackCompanyEnrichmentResult(
                status="failed",
                diagnostics=exc.diagnostics.to_dict(),
                error_message=str(exc),
            )

        normalized = tuple(
            company
            for company in (normalize_theirstack_company(payload) for payload in search_result.companies)
            if company is not None
        )

        persisted = []
        company_sources = []
        canonical_created_count = 0
        source_created_count = 0
        source_updated_count = 0
        links = []
        for company_record in normalized:
            persisted_record = upsert_theirstack_company_record(
                self.session,
                company_record,
                source_query=discovery_query,
            )
            company = persisted_record.company
            persisted.append(company)
            company_sources.append(persisted_record.company_source)
            canonical_created_count += 1 if persisted_record.created_company else 0
            source_created_count += 1 if persisted_record.created_source else 0
            source_updated_count += 1 if persisted_record.updated_source else 0
            if candidate_profile_id and link_to_profile:
                link_result = ensure_candidate_company_link(
                    self.session,
                    candidate_profile_id=candidate_profile_id,
                    company=company,
                    derivation_status="provider_enriched",
                    discovery_query=discovery_query,
                    search_queries_used=[discovery_query] if discovery_query else [],
                    provider_grounding_metadata=build_candidate_company_metadata(
                        company_record,
                        discovery_query=discovery_query,
                    ),
                    discovered_by="theirstack",
                    personal_source_urls=list(company_record.source_urls),
                )
                links.append(link_result.link)

        diagnostics = (search_result.diagnostics or TheirStackCompanySearchDiagnostics(enabled=True, requested_pages=1)).to_dict()
        diagnostics["normalizedCompanyCount"] = len(normalized)
        diagnostics["upsertedCompanyCount"] = len(persisted)
        diagnostics["canonicalCompanyUpsertedCount"] = len(persisted)
        diagnostics["canonicalCompanyCreatedCount"] = canonical_created_count
        diagnostics["canonicalCompanyUpdatedCount"] = 0
        diagnostics["companySourceCreatedCount"] = source_created_count
        diagnostics["companySourceUpdatedCount"] = source_updated_count
        diagnostics["companySourceCount"] = len(company_sources)
        diagnostics["linkedCandidateCompanyCount"] = len(links)
        return TheirStackCompanyEnrichmentResult(
            status="completed",
            companies=tuple(persisted),
            company_sources=tuple(company_sources),
            candidate_company_links=tuple(links),
            normalized_companies=normalized,
            diagnostics=diagnostics,
        )


def request_with_settings_defaults(
    request: TheirStackCompanySearchRequest,
    *,
    settings: Settings,
) -> TheirStackCompanySearchRequest:
    return replace(
        request,
        limit=request.limit if request.limit is not None else settings.theirstack_company_search_limit,
        max_pages=request.max_pages if request.max_pages is not None else settings.theirstack_company_search_max_pages,
    )


def job_listings_url_for(company: NormalizedCompanyEnrichment) -> str | None:
    if company.greenhouse_board_token:
        return canonical_greenhouse_jobs_api_url(company.greenhouse_board_token)
    return None


@dataclass(frozen=True)
class PersistedTheirStackCompanyRecord:
    company: Company
    company_source: CompanySource
    created_company: bool
    created_source: bool
    updated_source: bool


def upsert_theirstack_company_record(
    session: Session,
    company_record: NormalizedCompanyEnrichment,
    *,
    source_query: str | None = None,
) -> PersistedTheirStackCompanyRecord:
    existing_company = find_canonical_company(
        session,
        normalized_name=company_record.normalized_name,
        normalized_domain=company_record.domain,
        greenhouse_board_token=company_record.greenhouse_board_token,
        ashby_board_url=company_record.ashby_board_url,
        lever_slug=company_record.lever_slug,
    )
    company = upsert_canonical_company(
        session,
        name=company_record.name,
        normalized_name=company_record.normalized_name,
        domain=company_record.domain,
        normalized_domain=company_record.domain,
        website_url=company_record.website_url,
        job_listings_url=job_listings_url_for(company_record),
        description=company_record.description,
        headquarters_city=company_record.headquarters_city,
        headquarters_country=company_record.headquarters_country,
        source_urls=list(company_record.source_urls),
        source_summary=company_record.source_summary,
        data_confidence="medium",
        greenhouse_board_token=company_record.greenhouse_board_token,
        ashby_board_url=company_record.ashby_board_url,
        lever_slug=company_record.lever_slug,
    )
    company_source = find_existing_company_source(session, company_record, company=company)
    created = company_source is None
    if company_source is None:
        company_source = CompanySource(
            company=company,
            source_provider="theirstack",
            provider_type="company_source",
        )
        session.add(company_source)
    apply_theirstack_company_source_fields(company_source, company_record, source_query=source_query)
    session.flush()
    return PersistedTheirStackCompanyRecord(
        company=company,
        company_source=company_source,
        created_company=existing_company is None,
        created_source=created,
        updated_source=not created,
    )


def find_existing_company_source(
    session: Session,
    company_record: NormalizedCompanyEnrichment,
    *,
    company: Company,
) -> CompanySource | None:
    provider_company_id = provider_company_id_for(company_record)
    if provider_company_id:
        source = session.scalar(
            select(CompanySource).where(
                CompanySource.source_provider == "theirstack",
                CompanySource.provider_company_id == provider_company_id,
            )
        )
        if source is not None:
            return source
    source_url = primary_source_url_for(company_record)
    if source_url:
        source = session.scalar(
            select(CompanySource).where(
                CompanySource.source_provider == "theirstack",
                CompanySource.source_url == source_url,
            )
        )
        if source is not None:
            return source
    return session.scalar(
        select(CompanySource).where(
            CompanySource.source_provider == "theirstack",
            CompanySource.company_id == company.id,
        )
    )


def apply_theirstack_company_source_fields(
    company_source: CompanySource,
    company_record: NormalizedCompanyEnrichment,
    *,
    source_query: str | None,
) -> None:
    company_source.source_provider = "theirstack"
    company_source.provider_type = "company_source"
    company_source.provider_company_id = provider_company_id_for(company_record)
    company_source.source_result_id = company_source.provider_company_id
    company_source.source_url = primary_source_url_for(company_record)
    company_source.website_url = company_record.website_url
    company_source.linkedin_url = company_record.linkedin_url
    company_source.careers_url = company_record.source_urls[0] if company_record.source_urls else None
    company_source.source_query = source_query
    company_source.raw_metadata_json = company_record.raw_provider_metadata
    company_source.ats_metadata_json = {
        "greenhouseBoardToken": company_record.greenhouse_board_token,
        "ashbyBoardUrl": company_record.ashby_board_url,
        "leverSlug": company_record.lever_slug,
        "unsupportedAtsUrls": list(company_record.unsupported_ats_urls),
    }
    company_source.company_signals_json = {
        "industry": company_record.industry,
        "employeeCount": company_record.employee_count,
        "employeeCountRange": company_record.employee_count_range,
        "fundingStage": company_record.funding_stage,
        "totalFundingUsd": company_record.total_funding_usd,
        "technologyNames": list(company_record.technology_names),
        "technologySlugs": list(company_record.technology_slugs),
        "keywordSlugs": list(company_record.keyword_slugs),
        "numJobs": company_record.num_jobs,
        "numJobsFound": company_record.num_jobs_found,
        "numJobsLast30Days": company_record.num_jobs_last_30_days,
    }
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    company_source.last_seen_at = now
    company_source.last_synced_at = now
    company_source.is_active = True


def provider_company_id_for(company: NormalizedCompanyEnrichment) -> str | None:
    value = company.raw_provider_metadata.get("id")
    return str(value).strip() if value not in (None, "") else None


def primary_source_url_for(company: NormalizedCompanyEnrichment) -> str | None:
    return company.website_url or company.linkedin_url or next(iter(company.source_urls), None)


def build_candidate_company_metadata(
    company: NormalizedCompanyEnrichment,
    *,
    discovery_query: str | None,
) -> dict[str, Any]:
    return {
        "provider": "theirstack",
        "discoveryQuery": discovery_query,
        "atsInference": {
            "greenhouseBoardToken": company.greenhouse_board_token,
            "ashbyBoardUrl": company.ashby_board_url,
            "leverSlug": company.lever_slug,
            "unsupportedAtsUrls": list(company.unsupported_ats_urls),
        },
        "companyMetadata": {
            "linkedinUrl": company.linkedin_url,
            "industry": company.industry,
            "employeeCount": company.employee_count,
            "employeeCountRange": company.employee_count_range,
            "fundingStage": company.funding_stage,
            "totalFundingUsd": company.total_funding_usd,
            "technologyNames": list(company.technology_names),
            "technologySlugs": list(company.technology_slugs),
            "keywordSlugs": list(company.keyword_slugs),
            "numJobs": company.num_jobs,
            "numJobsFound": company.num_jobs_found,
            "numJobsLast30Days": company.num_jobs_last_30_days,
            "unsupportedAtsUrls": list(company.unsupported_ats_urls),
            "rawProviderMetadata": company.raw_provider_metadata,
        },
    }
