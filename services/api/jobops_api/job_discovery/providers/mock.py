from __future__ import annotations

import re
from datetime import date, datetime, timezone

from ...settings import Settings
from .base import JobSearchRequest, LiveJobSourceResult, ProviderDiagnostic, ProviderSearchOutcome, ProviderType


class MockJobDiscoveryProvider:
    provider_name = "mock"
    provider_type: ProviderType = "mock"

    def is_configured(self, settings: Settings) -> bool:
        return settings.model_provider.strip().lower() == "mock" or "mock" in settings.job_discovery_providers

    def search(self, request: JobSearchRequest, settings: Settings) -> ProviderSearchOutcome:
        results = build_mock_live_job_source_results(request.search_queries[:4])
        return ProviderSearchOutcome(
            results=results,
            diagnostics=[
                ProviderDiagnostic(
                    provider_name=self.provider_name,
                    provider_type=self.provider_type,
                    configured=True,
                    attempted=True,
                    result_count=len(results),
                    query=request.search_queries[0] if request.search_queries else None,
                )
            ],
            errors=[],
        )


def build_mock_live_job_source_results(search_queries: list[str]) -> list[LiveJobSourceResult]:
    query = search_queries[0] if search_queries else "mock job discovery"
    role_title = mock_role_title_from_query(query)
    secondary_role_title = f"Senior {role_title}" if not role_title.casefold().startswith("senior ") else f"Lead {role_title}"
    primary_slug = slugify_mock_value(role_title)
    secondary_slug = slugify_mock_value(secondary_role_title)
    return [
        LiveJobSourceResult(
            title=role_title,
            company_name="Example Mission Org",
            job_url=f"https://example-mission-org.example.test/jobs/{primary_slug}",
            source_provider="mock_job_source",
            provider_type="mock",
            source_result_id=f"mock-{primary_slug}",
            source_query=query,
            source_url=f"https://example-mission-org.example.test/jobs/{primary_slug}",
            provenance="mock",
            location="Remote US",
            remote_work_mode="remote",
            employment_type="Full-time",
            salary_min=150000,
            salary_max=190000,
            salary_currency="USD",
            salary_text="USD 150,000-190,000",
            description_excerpt=f"Mock provider-backed opening for {role_title}.",
            posting_date=date(2026, 5, 20),
            fit_summary="Mock result matching the current job search query.",
            url_verification_status="mock_verified",
            url_verification_checked_at=datetime.now(timezone.utc),
            url_verification_summary="Mock source result for local/test mode.",
        ),
        LiveJobSourceResult(
            title=secondary_role_title,
            company_name="Sample Growth Co",
            job_url=f"https://sample-growth-co.example.test/jobs/{secondary_slug}",
            source_provider="mock_job_source",
            provider_type="mock",
            source_result_id=f"mock-{secondary_slug}",
            source_query=query,
            source_url=f"https://sample-growth-co.example.test/jobs/{secondary_slug}",
            provenance="mock",
            location="Hybrid Example City",
            remote_work_mode="hybrid",
            employment_type="Full-time",
            salary_min=160000,
            salary_max=205000,
            salary_currency="USD",
            salary_text="USD 160,000-205,000",
            description_excerpt=f"Mock provider-backed opening for {secondary_role_title}.",
            posting_date=None,
            fit_summary="Mock result matching the current job search query.",
            url_verification_status="mock_verified",
            url_verification_checked_at=datetime.now(timezone.utc),
            url_verification_summary="Mock source result for local/test mode.",
        ),
    ]


def mock_role_title_from_query(query: str) -> str:
    cleaned = re.sub(r"\b(remote|hybrid|onsite|on-site|job|jobs|role|roles|opening|openings|apply|careers)\b", " ", query, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.;:-\"'")
    return cleaned or "Sample Role"


def slugify_mock_value(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "sample-role"
