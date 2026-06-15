from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import jobops_api.command_center as command_center_module
from jobops_api.company_sources.theirstack.ats import infer_ats_from_url
from jobops_api.company_sources.theirstack.client import TheirStackCompanySearchClient, TheirStackCompanySearchError
from jobops_api.company_sources.theirstack.models import TheirStackCompanySearchRequest
from jobops_api.company_sources.theirstack.normalizer import normalize_theirstack_company
from jobops_api.company_sources.theirstack.service import TheirStackCompanyEnrichmentService
from jobops_api.company_canonicalization import ensure_candidate_company_link, upsert_canonical_company
from jobops_api.db.models import Base, CandidateCompany, Company
from jobops_api.db.seed_profile import seed_public_profile
from jobops_api.settings import Settings


def test_theirstack_client_sends_post_bearer_auth_and_sanitized_diagnostics() -> None:
    calls: list[dict[str, Any]] = []

    def fake_post(url: str, headers: dict[str, str], body: bytes, timeout_seconds: float) -> tuple[int, dict[str, Any]]:
        calls.append(
            {
                "url": url,
                "headers": headers,
                "body": json.loads(body.decode("utf-8")),
                "timeout": timeout_seconds,
            }
        )
        return 200, {"companies": [{"name": "Hightouch", "domain": "hightouch.com"}], "total": 1}

    client = TheirStackCompanySearchClient(api_key="super-secret", timeout_seconds=7, http_post=fake_post)

    result = client.search_companies(
        TheirStackCompanySearchRequest(
            company_name_or=("Hightouch",),
            company_domain_or=("hightouch.com",),
            job_filters={"posted_at_max_age_days": 30},
            limit=5,
        )
    )

    assert calls[0]["url"] == "https://api.theirstack.com/v1/companies/search"
    assert calls[0]["headers"]["Authorization"] == "Bearer super-secret"
    assert calls[0]["body"]["company_name_or"] == ["Hightouch"]
    assert calls[0]["body"]["company_domain_or"] == ["hightouch.com"]
    assert calls[0]["body"]["job_filters"] == {"posted_at_max_age_days": 30}
    assert result.companies[0]["name"] == "Hightouch"
    diagnostics = result.diagnostics.to_dict()
    assert diagnostics["requestShape"]["job_filters"] == "<present>"
    assert "super-secret" not in json.dumps(diagnostics)


def test_theirstack_client_failure_has_sanitized_diagnostics() -> None:
    def fake_post(url: str, headers: dict[str, str], body: bytes, timeout_seconds: float) -> tuple[int, dict[str, Any]]:
        return 429, {"error": "rate limit"}

    client = TheirStackCompanySearchClient(api_key="super-secret", http_post=fake_post)

    with pytest.raises(TheirStackCompanySearchError) as exc:
        client.search_companies(TheirStackCompanySearchRequest(company_name_or=("Hightouch",)))

    diagnostics = exc.value.diagnostics.to_dict()
    assert diagnostics["failedPages"] == 1
    assert diagnostics["errorType"] == "http_error"
    assert "super-secret" not in json.dumps(diagnostics)


def test_theirstack_client_paginates_by_page() -> None:
    requested_pages: list[int] = []

    def fake_post(url: str, headers: dict[str, str], body: bytes, timeout_seconds: float) -> tuple[int, dict[str, Any]]:
        parsed = json.loads(body.decode("utf-8"))
        requested_pages.append(parsed["page"])
        return 200, {"companies": [{"name": f"Company {parsed['page']}"}], "total": 3}

    client = TheirStackCompanySearchClient(api_key="secret", http_post=fake_post)

    result = client.search_companies(TheirStackCompanySearchRequest(limit=1, page=2, max_pages=3))

    assert requested_pages == [2, 3, 4]
    assert [company["name"] for company in result.companies] == ["Company 2", "Company 3", "Company 4"]
    assert result.diagnostics.fetched_pages == 3


def test_theirstack_normalizer_extracts_company_fields_and_provider_metadata() -> None:
    normalized = normalize_theirstack_company(theirstack_payload())

    assert normalized is not None
    assert normalized.name == "Hightouch"
    assert normalized.domain == "hightouch.com"
    assert normalized.website_url == "https://hightouch.com"
    assert normalized.description == "Customer data platform."
    assert normalized.num_jobs_found == 42
    assert normalized.greenhouse_board_token == "hightouch"
    assert normalized.unsupported_ats_urls == ("https://example.myworkdayjobs.com/Hightouch",)
    assert normalized.raw_provider_metadata["provider"] == "theirstack"
    assert "api_key" not in normalized.raw_provider_metadata


def test_theirstack_normalizer_missing_optional_fields_does_not_crash() -> None:
    normalized = normalize_theirstack_company({"name": "Sparse Co"})

    assert normalized is not None
    assert normalized.name == "Sparse Co"
    assert normalized.source_urls == ()


def test_theirstack_ats_inference_recognizes_supported_and_unsupported_urls() -> None:
    greenhouse_public = infer_ats_from_url("https://job-boards.greenhouse.io/hightouch/jobs/123")
    greenhouse_api = infer_ats_from_url("https://boards-api.greenhouse.io/v1/boards/hightouch/jobs/123")
    ashby = infer_ats_from_url("https://jobs.ashbyhq.com/example/abc")
    lever = infer_ats_from_url("https://jobs.lever.co/example/abc")
    workday = infer_ats_from_url("https://example.myworkdayjobs.com/example/job/123")

    assert greenhouse_public.greenhouse_board_token == "hightouch"
    assert greenhouse_api.greenhouse_board_token == "hightouch"
    assert ashby.ashby_board_url == "https://jobs.ashbyhq.com/example"
    assert lever.lever_slug == "example"
    assert workday.unsupported_ats_urls == ("https://example.myworkdayjobs.com/example/job/123",)


def test_theirstack_enrichment_upserts_company_without_linking_profile(tmp_path: Path) -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        service = TheirStackCompanyEnrichmentService(
            session=session,
            settings=make_settings(tmp_path),
            client=FakeTheirStackClient([theirstack_payload()]),
        )

        result = service.search_and_upsert_companies(
            TheirStackCompanySearchRequest(company_name_or=("Hightouch",)),
            discovery_query="cdp companies",
        )
        session.commit()

    with Session(engine) as session:
        company = session.scalar(select(Company).where(Company.name == "Hightouch"))
        assert result.status == "completed"
        assert company is not None
        assert company.greenhouse_board_token == "hightouch"
        assert company.job_listings_url == "https://boards-api.greenhouse.io/v1/boards/hightouch/jobs"
        assert session.scalar(select(CandidateCompany)) is None


def test_theirstack_enrichment_explicitly_links_candidate_company_with_metadata(tmp_path: Path) -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        service = TheirStackCompanyEnrichmentService(
            session=session,
            settings=make_settings(tmp_path),
            client=FakeTheirStackClient([theirstack_payload()]),
        )

        result = service.search_and_upsert_companies(
            TheirStackCompanySearchRequest(company_domain_or=("hightouch.com",)),
            candidate_profile_id=profile.id,
            link_to_profile=True,
            discovery_query="cdp companies",
        )
        session.commit()

    with Session(engine) as session:
        link = session.scalar(select(CandidateCompany).join(Company).where(Company.name == "Hightouch"))
        assert result.status == "completed"
        assert link is not None
        assert link.provider_grounding_metadata["provider"] == "theirstack"
        assert link.provider_grounding_metadata["discoveryQuery"] == "cdp companies"
        assert link.provider_grounding_metadata["atsInference"]["greenhouseBoardToken"] == "hightouch"
        assert link.provider_grounding_metadata["companyMetadata"]["numJobsFound"] == 42
        assert "secret" not in json.dumps(link.provider_grounding_metadata).casefold()


def test_theirstack_enrichment_does_not_downgrade_existing_company_metadata(tmp_path: Path) -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        existing = upsert_canonical_company(
            session,
            name="Hightouch",
            website_url="https://hightouch.com",
            description="Richer existing description.",
            source_summary="Human-reviewed source summary.",
            greenhouse_board_token="hightouch",
        )
        session.commit()
        existing_id = existing.id

    with Session(engine) as session:
        service = TheirStackCompanyEnrichmentService(
            session=session,
            settings=make_settings(tmp_path),
            client=FakeTheirStackClient([theirstack_payload(description="Short fallback.")]),
        )

        service.search_and_upsert_companies(TheirStackCompanySearchRequest(company_domain_or=("hightouch.com",)))
        session.commit()

    with Session(engine) as session:
        companies = list(session.scalars(select(Company)))
        company = session.get(Company, existing_id)
        assert len(companies) == 1
        assert company is not None
        assert company.description == "Richer existing description."
        assert company.source_summary == "Human-reviewed source summary."


def test_theirstack_enrichment_captures_ashby_and_lever_metadata_without_duplicates(tmp_path: Path) -> None:
    payloads = [
        {
            "name": "Ashby Co",
            "domain": "ashbyco.example",
            "jobs_found": [{"url": "https://jobs.ashbyhq.com/ashbyco/abc"}],
        },
        {
            "name": "Lever Co",
            "domain": "leverco.example",
            "jobs_found": [{"url": "https://jobs.lever.co/leverco/abc"}],
        },
    ]
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        service = TheirStackCompanyEnrichmentService(
            session=session,
            settings=make_settings(tmp_path),
            client=FakeTheirStackClient(payloads),
        )

        first = service.search_and_upsert_companies(
            TheirStackCompanySearchRequest(company_name_or=("Ashby Co", "Lever Co")),
            candidate_profile_id=profile.id,
            link_to_profile=True,
            discovery_query="ats companies",
        )
        second = service.search_and_upsert_companies(
            TheirStackCompanySearchRequest(company_name_or=("Ashby Co", "Lever Co")),
            candidate_profile_id=profile.id,
            link_to_profile=True,
            discovery_query="ats companies",
        )
        session.commit()

    with Session(engine) as session:
        ashby = session.scalar(select(Company).where(Company.name == "Ashby Co"))
        lever = session.scalar(select(Company).where(Company.name == "Lever Co"))
        assert first.status == "completed"
        assert second.status == "completed"
        assert ashby is not None
        assert ashby.ashby_board_url == "https://jobs.ashbyhq.com/ashbyco"
        assert lever is not None
        assert lever.lever_slug == "leverco"
        assert len(session.scalars(select(Company)).all()) == 2
        assert len(session.scalars(select(CandidateCompany)).all()) == 2


def test_theirstack_enrichment_dedupes_by_existing_lever_slug(tmp_path: Path) -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        existing = upsert_canonical_company(session, name="Existing Lever Name", lever_slug="leverco")
        session.commit()
        existing_id = existing.id

    with Session(engine) as session:
        service = TheirStackCompanyEnrichmentService(
            session=session,
            settings=make_settings(tmp_path),
            client=FakeTheirStackClient(
                [
                    {
                        "name": "Lever Co",
                        "jobs_found": [{"url": "https://jobs.lever.co/leverco/abc"}],
                    }
                ]
            ),
        )

        service.search_and_upsert_companies(TheirStackCompanySearchRequest(company_name_or=("Lever Co",)))
        session.commit()

    with Session(engine) as session:
        companies = list(session.scalars(select(Company)))
        assert len(companies) == 1
        assert companies[0].id == existing_id
        assert companies[0].lever_slug == "leverco"


def test_theirstack_enrichment_unavailable_when_disabled(tmp_path: Path) -> None:
    engine = create_seeded_engine()
    settings = make_settings(tmp_path, api_key=None, enabled=False)
    with Session(engine) as session:
        service = TheirStackCompanyEnrichmentService(session=session, settings=settings)

        result = service.search_and_upsert_companies(TheirStackCompanySearchRequest(company_name_or=("Hightouch",)))

    assert result.status == "unavailable"
    assert result.diagnostics["enabled"] is False
    assert "api key" in result.error_message.casefold()


class FakeTheirStackClient:
    def __init__(self, companies: list[dict[str, Any]]) -> None:
        self.companies = companies

    def search_companies(self, request: TheirStackCompanySearchRequest):
        from jobops_api.company_sources.theirstack.models import (
            TheirStackCompanySearchDiagnostics,
            TheirStackCompanySearchResult,
        )

        return TheirStackCompanySearchResult(
            status="completed",
            companies=tuple(self.companies),
            diagnostics=TheirStackCompanySearchDiagnostics(
                enabled=True,
                requested_pages=request.max_pages,
                fetched_pages=1,
                raw_company_count=len(self.companies),
                request_shape=request.sanitized_shape(),
            ),
        )


def theirstack_payload(*, description: str = "Customer data platform.") -> dict[str, Any]:
    return {
        "id": "company_123",
        "name": "Hightouch",
        "domain": "hightouch.com",
        "website_url": "https://hightouch.com",
        "linkedin_url": "https://www.linkedin.com/company/hightouch",
        "description": description,
        "headquarters_city": "San Francisco",
        "headquarters_country": "US",
        "industry": "Data",
        "employee_count": 400,
        "employee_count_range": "201-500",
        "funding_stage": "Series C",
        "total_funding_usd": 92000000,
        "technologies": [{"name": "Snowflake", "slug": "snowflake"}],
        "keywords": ["cdp", "data-activation"],
        "num_jobs_found": 42,
        "num_jobs_last_30_days": 12,
        "jobs_found": [
            {"url": "https://job-boards.greenhouse.io/hightouch/jobs/123"},
            {"url": "https://example.myworkdayjobs.com/Hightouch"},
        ],
    }


def create_seeded_engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_public_profile(
            session,
            {
                "slug": "rebekah-love",
                "displayName": "Rebekah Love",
                "headline": "Candidate profile setup in progress",
                "summary": "Verified public profile facts are being reviewed before publication.",
                "profileStatus": "draft",
            },
            hostname="rebekahalove.dev",
        )
        session.commit()
    return engine


def make_settings(
    repo_root: Path,
    *,
    api_key: str | None = "secret-theirstack-key",
    enabled: bool = True,
) -> Settings:
    return Settings(
        app_env="test",
        cheap_model="mock-cheap",
        company_discovery_search_grounding_enabled=True,
        database_url=None,
        default_model="mock-default",
        gemini_api_key=None,
        model_provider="mock",
        profile_intake_save_artifacts=False,
        profile_intake_save_raw_text=False,
        repo_root=repo_root,
        theirstack_api_key=api_key,
        theirstack_company_search_enabled=enabled,
    )
