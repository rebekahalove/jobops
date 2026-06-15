from __future__ import annotations

from dataclasses import replace
from typing import Any

from sqlalchemy.orm import Session

from ...company_canonicalization import ensure_candidate_company_link, upsert_canonical_company
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
            diagnostics = TheirStackCompanySearchDiagnostics(
                enabled=False,
                requested_pages=max(1, request.max_pages),
                skipped_pages=max(1, request.max_pages),
                request_shape=request.sanitized_shape(),
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
        effective_request = replace(
            request,
            limit=request.limit or self.settings.theirstack_company_search_limit,
            max_pages=request.max_pages or self.settings.theirstack_company_search_max_pages,
        )
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
        links = []
        for company_record in normalized:
            company = upsert_canonical_company(
                self.session,
                name=company_record.name,
                normalized_name=company_record.normalized_name,
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
            persisted.append(company)
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
        diagnostics["linkedCandidateCompanyCount"] = len(links)
        return TheirStackCompanyEnrichmentResult(
            status="completed",
            companies=tuple(persisted),
            candidate_company_links=tuple(links),
            normalized_companies=normalized,
            diagnostics=diagnostics,
        )


def job_listings_url_for(company: NormalizedCompanyEnrichment) -> str | None:
    if company.greenhouse_board_token:
        return canonical_greenhouse_jobs_api_url(company.greenhouse_board_token)
    return None


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
