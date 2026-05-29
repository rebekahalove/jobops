from __future__ import annotations

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
    return [
        LiveJobSourceResult(
            title="Applied AI Engineer",
            company_name="Civic AI Labs",
            job_url="https://civic-ai-labs.example.test/jobs/applied-ai-engineer",
            source_provider="mock_job_source",
            provider_type="mock",
            source_result_id="mock-civic-ai-applied",
            source_query=query,
            source_url="https://civic-ai-labs.example.test/jobs/applied-ai-engineer",
            provenance="mock",
            location="Remote US",
            remote_work_mode="remote",
            employment_type="Full-time",
            salary_text="$150k-$190k",
            description_excerpt="Build applied AI workflows for civic teams.",
            posting_date=date(2026, 5, 20),
            fit_summary="Matches applied AI, platform, and public-interest technology goals.",
            url_verification_status="mock_verified",
            url_verification_checked_at=datetime.now(timezone.utc),
            url_verification_summary="Mock source result for local/test mode.",
        ),
        LiveJobSourceResult(
            title="AI Platform Engineer",
            company_name="Open Data Works",
            job_url="https://open-data-works.example.test/jobs/ai-platform-engineer",
            source_provider="mock_job_source",
            provider_type="mock",
            source_result_id="mock-open-data-platform",
            source_query=query,
            source_url="https://open-data-works.example.test/jobs/ai-platform-engineer",
            provenance="mock",
            location="Hybrid NYC",
            remote_work_mode="hybrid",
            employment_type="Full-time",
            salary_text="$160k-$205k",
            description_excerpt="Own LLM evaluation, retrieval, and deployment tooling.",
            posting_date=None,
            fit_summary="Strong fit for AI platform engineering and RAG evaluation experience.",
            url_verification_status="mock_verified",
            url_verification_checked_at=datetime.now(timezone.utc),
            url_verification_summary="Mock source result for local/test mode.",
        ),
    ]

