from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TheirStackCompanySearchRequest:
    company_name_or: tuple[str, ...] = ()
    company_name_partial_match_or: tuple[str, ...] = ()
    company_domain_or: tuple[str, ...] = ()
    company_country_code_or: tuple[str, ...] = ()
    company_description_pattern_or: tuple[str, ...] = ()
    company_technology_slug_or: tuple[str, ...] = ()
    company_technology_slug_and: tuple[str, ...] = ()
    company_keyword_slug_or: tuple[str, ...] = ()
    job_filters: dict[str, Any] = field(default_factory=dict)
    limit: int = 25
    page: int = 1
    max_pages: int = 1
    include_total_results: bool = True

    def to_api_body(self, *, page: int | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "limit": self.limit,
            "page": page or self.page,
        }
        tuple_fields = {
            "company_name_or": self.company_name_or,
            "company_name_partial_match_or": self.company_name_partial_match_or,
            "company_domain_or": self.company_domain_or,
            "company_country_code_or": self.company_country_code_or,
            "company_description_pattern_or": self.company_description_pattern_or,
            "company_technology_slug_or": self.company_technology_slug_or,
            "company_technology_slug_and": self.company_technology_slug_and,
            "company_keyword_slug_or": self.company_keyword_slug_or,
        }
        for key, values in tuple_fields.items():
            cleaned = [value.strip() for value in values if isinstance(value, str) and value.strip()]
            if cleaned:
                body[key] = cleaned
        if self.job_filters:
            body["job_filters"] = self.job_filters
        if self.include_total_results:
            body["include_total_results"] = True
        return body

    def sanitized_shape(self) -> dict[str, Any]:
        body = self.to_api_body(page=self.page)
        return {
            key: ("<present>" if key == "job_filters" else value)
            for key, value in body.items()
            if key not in {"api_key", "authorization", "Authorization"}
        }


@dataclass(frozen=True)
class TheirStackCompanySearchDiagnostics:
    enabled: bool
    requested_pages: int
    fetched_pages: int = 0
    failed_pages: int = 0
    skipped_pages: int = 0
    raw_company_count: int = 0
    normalized_company_count: int = 0
    total_companies: int | None = None
    request_shape: dict[str, Any] = field(default_factory=dict)
    credit_note: str = "TheirStack may consume credits per returned company."
    error_type: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "requestedPages": self.requested_pages,
            "fetchedPages": self.fetched_pages,
            "failedPages": self.failed_pages,
            "skippedPages": self.skipped_pages,
            "rawCompanyCount": self.raw_company_count,
            "normalizedCompanyCount": self.normalized_company_count,
            "totalCompanies": self.total_companies,
            "requestShape": self.request_shape,
            "creditNote": self.credit_note,
            "errorType": self.error_type,
            "errorMessage": self.error_message,
        }


@dataclass(frozen=True)
class TheirStackCompanySearchResult:
    status: str
    companies: tuple[dict[str, Any], ...] = ()
    diagnostics: TheirStackCompanySearchDiagnostics | None = None


@dataclass(frozen=True)
class NormalizedCompanyEnrichment:
    name: str
    normalized_name: str | None = None
    domain: str | None = None
    website_url: str | None = None
    linkedin_url: str | None = None
    description: str | None = None
    headquarters_city: str | None = None
    headquarters_country: str | None = None
    industry: str | None = None
    employee_count: int | None = None
    employee_count_range: str | None = None
    funding_stage: str | None = None
    total_funding_usd: int | None = None
    technology_names: tuple[str, ...] = ()
    technology_slugs: tuple[str, ...] = ()
    keyword_slugs: tuple[str, ...] = ()
    num_jobs: int | None = None
    num_jobs_found: int | None = None
    num_jobs_last_30_days: int | None = None
    source_urls: tuple[str, ...] = ()
    source_summary: str | None = None
    greenhouse_board_token: str | None = None
    ashby_board_url: str | None = None
    lever_slug: str | None = None
    unsupported_ats_urls: tuple[str, ...] = ()
    raw_provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TheirStackCompanyEnrichmentResult:
    status: str
    companies: tuple[Any, ...] = ()
    candidate_company_links: tuple[Any, ...] = ()
    normalized_companies: tuple[NormalizedCompanyEnrichment, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None

