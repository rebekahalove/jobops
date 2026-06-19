from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from jobops_api.company_discovery import CompanyDiscoveryRequest, run_company_discovery
from jobops_api.company_sources.theirstack.models import (
    TheirStackCompanySearchDiagnostics,
    TheirStackCompanySearchRequest,
    TheirStackCompanySearchResult,
)
from jobops_api.company_sync import (
    derive_company_sync_signatures,
    sync_theirstack_company_signatures,
    upsert_theirstack_company_sync_signature,
)
from jobops_api.model_connector import ModelRequest, ModelResponse
from jobops_api.db.models import (
    Base,
    CandidateCompany,
    CandidateProfile,
    Company,
    CompanySource,
    CompanySyncRun,
    CompanySyncSignature,
    JobListing,
    RoleTarget,
)
from jobops_api.db.seed_profile import seed_public_profile
from jobops_api.settings import Settings


def test_company_sync_signature_run_and_source_models_persist(tmp_path: Path) -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        company = Company(name="Example AI", normalized_name="example ai", domain="example.ai", normalized_domain="example.ai")
        session.add(company)
        session.flush()
        source = CompanySource(
            company_id=company.id,
            source_provider="theirstack",
            provider_type="company_source",
            provider_company_id="company_123",
            raw_metadata_json={"numJobsFound": 3},
            ats_metadata_json={"greenhouseBoardToken": "example"},
        )
        signature = CompanySyncSignature(
            provider_name="theirstack",
            provider_type="company_source",
            sync_kind="company_search",
            sync_key="theirstack:company:test",
            query_text="Example AI",
            query_kind="admin_seed",
        )
        run = CompanySyncRun(
            company_sync_signature=signature,
            sync_key=signature.sync_key,
            provider_name="theirstack",
            provider_type="company_source",
            sync_kind="company_search",
            query_text="Example AI",
            query_kind="admin_seed",
            status="completed",
            completed_at=datetime.now(UTC),
            raw_result_count=1,
            normalized_count=1,
            created_count=1,
        )
        session.add_all([source, signature, run])
        session.commit()

    with Session(engine) as session:
        assert session.scalar(select(CompanySource).where(CompanySource.provider_company_id == "company_123")) is not None
        assert session.scalar(select(CompanySyncSignature).where(CompanySyncSignature.sync_key == "theirstack:company:test")) is not None
        assert session.scalar(select(CompanySyncRun).where(CompanySyncRun.raw_result_count == 1)) is not None


def test_manual_upsert_creates_theirstack_company_signature_without_calling_provider(tmp_path: Path) -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        signature = upsert_theirstack_company_sync_signature(
            session,
            query_text="AI companies hiring engineers",
            query_kind="admin_seed",
            request=TheirStackCompanySearchRequest(job_filters={"job_title_pattern_or": ["AI Engineer"]}, limit=10, max_pages=2),
            results_per_page=10,
            max_pages=2,
        )

        assert signature.provider_name == "theirstack"
        assert signature.provider_type == "company_source"
        assert signature.sync_kind == "company_search"
        assert signature.criteria_json["theirstackRequest"]["job_filters"] == {"job_title_pattern_or": ["AI Engineer"]}
        assert signature.criteria_json["requestShape"]["job_filters"] == "<present>"
        assert signature.criteria_json["companySyncSignatureId"] == signature.id
        assert len(session.scalars(select(CompanySyncRun)).all()) == 0


def test_sync_theirstack_company_signature_upserts_company_source_and_updates_status(tmp_path: Path) -> None:
    engine = create_seeded_engine()
    fake_client = FakeTheirStackClient([theirstack_payload()])
    with Session(engine) as session:
        signature = upsert_theirstack_company_sync_signature(
            session,
            query_text="data activation companies",
            request=TheirStackCompanySearchRequest(company_name_or=("Hightouch",), limit=5, max_pages=1),
            results_per_page=5,
            max_pages=1,
        )
        results = sync_theirstack_company_signatures(
            session,
            settings=make_settings(tmp_path),
            signature_ids=[signature.id],
            enabled_only=False,
            force=True,
            client=fake_client,
        )
        signature_id = signature.id
        session.commit()

    with Session(engine) as session:
        assert results[0].status == "completed"
        assert results[0].raw_result_count == 1
        assert results[0].normalized_count == 1
        assert fake_client.requests[0].company_name_or == ("Hightouch",)
        assert session.scalar(select(Company).where(Company.name == "Hightouch")) is not None
        company_source = session.scalar(select(CompanySource).where(CompanySource.provider_company_id == "company_123"))
        assert company_source is not None
        assert company_source.ats_metadata_json["greenhouseBoardToken"] == "hightouch"
        run = session.scalar(select(CompanySyncRun).where(CompanySyncRun.company_sync_signature_id == signature_id))
        assert run.created_count == 1
        assert run.updated_count == 0
        assert run.diagnostics_json["canonicalCompanyCreatedCount"] == 1
        assert run.diagnostics_json["companySourceCreatedCount"] == 1
        assert run.diagnostics_json["companySourceUpdatedCount"] == 0
        refreshed_signature = session.get(CompanySyncSignature, signature_id)
        assert refreshed_signature.last_status == "completed"
        assert refreshed_signature.last_raw_result_count == 1


def test_sync_reconstructs_saved_request_and_cli_max_pages_only_bounds_pages(tmp_path: Path) -> None:
    engine = create_seeded_engine()
    fake_client = FakeTheirStackClient([theirstack_payload()])
    with Session(engine) as session:
        signature = upsert_theirstack_company_sync_signature(
            session,
            query_text="data activation companies",
            request=TheirStackCompanySearchRequest(
                company_name_or=("Hightouch",),
                job_filters={"job_title_pattern_or": ["Data Engineer"]},
                limit=7,
                max_pages=3,
            ),
        )
        results = sync_theirstack_company_signatures(
            session,
            settings=make_settings(tmp_path),
            signature_ids=[signature.id],
            enabled_only=False,
            force=True,
            max_pages=1,
            client=fake_client,
        )

        assert results[0].status == "completed"
        assert fake_client.requests[0].company_name_or == ("Hightouch",)
        assert fake_client.requests[0].job_filters == {"job_title_pattern_or": ["Data Engineer"]}
        assert fake_client.requests[0].limit == 7
        assert fake_client.requests[0].max_pages == 1


def test_sync_theirstack_company_signature_skips_fresh_unless_forced(tmp_path: Path) -> None:
    engine = create_seeded_engine()
    fake_client = FakeTheirStackClient([theirstack_payload()])
    with Session(engine) as session:
        signature = upsert_theirstack_company_sync_signature(
            session,
            query_text="data activation companies",
            request=TheirStackCompanySearchRequest(company_name_or=("Hightouch",)),
            freshness_hours=168,
        )
        sync_theirstack_company_signatures(
            session,
            settings=make_settings(tmp_path),
            signature_ids=[signature.id],
            enabled_only=False,
            force=True,
            client=fake_client,
        )
        second = sync_theirstack_company_signatures(
            session,
            settings=make_settings(tmp_path),
            signature_ids=[signature.id],
            enabled_only=False,
            force=False,
            client=fake_client,
        )

        assert second[0].status == "skipped_fresh"
        assert len(fake_client.requests) == 1
        assert len(session.scalars(select(CompanySyncRun)).all()) == 2


def test_sync_theirstack_company_signature_persists_failure_without_crashing_batch(tmp_path: Path) -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        signature = upsert_theirstack_company_sync_signature(
            session,
            query_text="data activation companies",
            request=TheirStackCompanySearchRequest(company_name_or=("Hightouch",)),
        )
        results = sync_theirstack_company_signatures(
            session,
            settings=make_settings(tmp_path, api_key=None),
            signature_ids=[signature.id],
            enabled_only=False,
            force=True,
        )
        signature_id = signature.id
        session.commit()

    with Session(engine) as session:
        assert results[0].error == "TheirStack company search is disabled or missing an API key."
        run = session.scalar(select(CompanySyncRun).where(CompanySyncRun.company_sync_signature_id == signature_id))
        assert run.status == "failed"
        assert "API key" in run.error


def test_model_planned_profile_signature_derivation_calls_planner_and_persists_criteria() -> None:
    engine = create_seeded_engine()
    planner = FakePlannerConnector(
        {
            "assistantMessage": "Planned one grounded company sync signature.",
            "signatures": [
                {
                    "queryText": "AI platform engineering companies",
                    "queryKind": "target_role_company_discovery",
                    "rationale": "Derived from target titles.",
                    "sourceFieldsUsed": ["target_titles", "role_families"],
                    "grounding": [{"field": "RoleTarget.target_titles", "value": "AI Platform Engineer"}],
                    "theirstackRequest": {
                        "jobFilters": {
                            "job_title_pattern_or": ["AI Platform Engineer"],
                            "posted_at_max_age_days": 30,
                        },
                        "limit": 99,
                        "maxPages": 5,
                    },
                    "confidence": "medium",
                    "needsReview": False,
                }
            ],
            "rejectedIdeas": [],
        }
    )
    with Session(engine) as session:
        profile = seeded_profile(session)
        session.add(
            RoleTarget(
                candidate_profile_id=profile.id,
                target_titles=["AI Platform Engineer"],
                role_families=["Developer Tools"],
                preferred_locations=["Remote US"],
                work_modes=["remote"],
                constraints={"industries": ["climate tech"], "avoid": ["defense"]},
                review_status="reviewed",
                is_active=True,
            )
        )
        result = derive_company_sync_signatures(
            session,
            candidate_slug=profile.slug,
            latest_user_request="derive company sync signatures from my targets",
            connector=planner,
            limit=5,
            results_per_page=25,
            max_pages=1,
        )

        assert len(result.signatures) == 1
        assert len(planner.requests) == 1
        signature = result.signatures[0]
        request = signature.criteria_json["theirstackRequest"]
        assert request["job_filters"]["job_title_pattern_or"] == ["AI Platform Engineer"]
        assert request["job_filters"]["posted_at_max_age_days"] == 30
        assert request["limit"] == 25
        assert signature.max_pages == 1
        assert signature.criteria_json["modelPlanning"]["rationale"] == "Derived from target titles."
        assert signature.criteria_json["modelPlanning"]["grounding"][0]["value"] == "AI Platform Engineer"
        assert signature.criteria_json["modelPlanning"]["validationIssues"][0]["code"] == "limit_clamped"
        assert len(session.scalars(select(CompanySyncRun)).all()) == 0


def test_model_planned_ungrounded_signature_persists_needs_review_without_provider_call() -> None:
    engine = create_seeded_engine()
    planner = FakePlannerConnector(
        {
            "assistantMessage": "Planner proposed an ungrounded idea.",
            "signatures": [
                {
                    "queryText": "Defense robotics companies",
                    "queryKind": "target_role_company_discovery",
                    "rationale": "Not grounded enough.",
                    "sourceFieldsUsed": ["target_titles"],
                    "grounding": [],
                    "theirstackRequest": {
                        "companyDescriptionPatternOr": ["defense robotics"],
                        "jobFilters": {"job_title_pattern_or": ["Weapons Engineer"], "posted_at_max_age_days": 30},
                        "limit": 25,
                        "maxPages": 1,
                    },
                    "confidence": "low",
                    "needsReview": True,
                }
            ],
            "rejectedIdeas": [{"queryText": "Defense robotics companies", "reason": "Not grounded in profile."}],
        }
    )
    with Session(engine) as session:
        profile = seeded_profile(session)
        session.add(
            RoleTarget(
                candidate_profile_id=profile.id,
                target_titles=["AI Platform Engineer"],
                role_families=["Developer Tools"],
                review_status="reviewed",
                is_active=True,
            )
        )
        result = derive_company_sync_signatures(
            session,
            candidate_slug=profile.slug,
            latest_user_request="derive company sync signatures from my targets",
            connector=planner,
            limit=5,
        )

        assert len(result.signatures) == 1
        signature = result.signatures[0]
        assert signature.verification_status == "needs_review"
        assert signature.enabled is False
        assert signature.criteria_json["modelPlanning"]["rejectedIdeas"][0]["reason"] == "Not grounded in profile."
        assert len(session.scalars(select(CompanySyncRun)).all()) == 0


def test_model_planned_duplicate_signatures_dedupe_by_sync_key() -> None:
    engine = create_seeded_engine()
    signature_payload = {
        "queryText": "AI platform engineering companies",
        "queryKind": "target_role_company_discovery",
        "rationale": "Derived from target titles.",
        "sourceFieldsUsed": ["target_titles"],
        "grounding": [{"field": "RoleTarget.target_titles", "value": "AI Platform Engineer"}],
        "theirstackRequest": {
            "jobFilters": {"job_title_pattern_or": ["AI Platform Engineer"], "posted_at_max_age_days": 30},
            "limit": 25,
            "maxPages": 1,
        },
        "confidence": "medium",
        "needsReview": False,
    }
    planner = FakePlannerConnector({"assistantMessage": "Duplicate signatures.", "signatures": [signature_payload, signature_payload], "rejectedIdeas": []})
    with Session(engine) as session:
        profile = seeded_profile(session)
        session.add(
            RoleTarget(
                candidate_profile_id=profile.id,
                target_titles=["AI Platform Engineer"],
                role_families=["Developer Tools"],
                review_status="reviewed",
                is_active=True,
            )
        )
        result = derive_company_sync_signatures(session, candidate_slug=profile.slug, connector=planner, limit=5)

        assert len(result.signatures) == 1
        assert len(session.scalars(select(CompanySyncSignature)).all()) == 1


def test_derive_job_listing_signatures_dedupes_by_company_and_prioritizes_missing_metadata() -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        company = Company(name="Sparse Co", normalized_name="sparse co")
        session.add(company)
        session.flush()
        session.add_all(
            [
                JobListing(company_id=company.id, company_name="Sparse Co", title="AI Engineer", is_active=True),
                JobListing(company_id=company.id, company_name="Sparse Co", title="ML Engineer", is_active=True),
            ]
        )

        result = derive_company_sync_signatures(
            session,
            from_job_listings=True,
            missing_company_metadata_only=True,
            active_jobs_only=True,
            min_active_jobs=1,
            limit=10,
        )

        assert len(result.signatures) == 1
        signature = result.signatures[0]
        assert signature.query_kind == "job_listing_company_enrichment"
        assert signature.criteria_json["derivation"]["activeJobCount"] == 2
        assert "domain" in signature.criteria_json["derivation"]["missingMetadataFields"]


def test_company_discovery_uses_company_source_cache_before_model_fallback(tmp_path: Path) -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = seeded_profile(session)
        company = Company(
            name="Civic AI Labs",
            normalized_name="civic ai labs",
            domain="civic.ai",
            normalized_domain="civic.ai",
            description="Progressive politics AI engineering company.",
            source_summary="TheirStack company source found AI engineering hiring signals.",
        )
        source = CompanySource(
            company=company,
            source_provider="theirstack",
            provider_type="company_source",
            provider_company_id="civic_ai",
            source_query="progressive politics AI engineers",
            company_signals_json={"keywordSlugs": ["progressive-politics", "ai"]},
            last_synced_at=datetime.now(UTC),
            is_active=True,
        )
        session.add_all([company, source])
        session.commit()

        result = run_company_discovery(
            CompanyDiscoveryRequest(
                latest_user_message="Find companies in progressive politics hiring AI engineers.",
                candidate_profile_slug=profile.slug,
            ),
            db_session=session,
            settings=make_settings(tmp_path, enabled=False, api_key=None),
        )
        session.commit()

    with Session(engine) as session:
        assert result.status_code == 200
        assert result.body["result"]["sourcePath"] == "canonical_company_cache"
        link = session.scalar(select(CandidateCompany).join(Company).where(Company.name == "Civic AI Labs"))
        assert link is not None
        assert link.discovered_by == "canonical_company_cache"
        assert link.provider_grounding_metadata["dataOriginSource"] == "company_sync"


def test_company_discovery_stale_cache_does_not_short_circuit_fallback(tmp_path: Path) -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = seeded_profile(session)
        company = Company(
            name="Stale Civic AI Labs",
            normalized_name="stale civic ai labs",
            domain="stale-civic.ai",
            normalized_domain="stale-civic.ai",
            description="Progressive politics AI engineering company.",
            source_summary="Old TheirStack company source found AI engineering hiring signals.",
        )
        source = CompanySource(
            company=company,
            source_provider="theirstack",
            provider_type="company_source",
            provider_company_id="stale_civic_ai",
            source_query="progressive politics AI engineers",
            company_signals_json={"keywordSlugs": ["progressive-politics", "ai"]},
            last_synced_at=datetime.now(UTC) - timedelta(days=60),
            is_active=True,
        )
        session.add_all([company, source])
        session.commit()

        result = run_company_discovery(
            CompanyDiscoveryRequest(
                latest_user_message="Find companies in progressive politics hiring AI engineers.",
                candidate_profile_slug=profile.slug,
            ),
            db_session=session,
            settings=make_settings(tmp_path, enabled=False, api_key=None),
        )
        session.commit()

    with Session(engine) as session:
        assert result.status_code == 200
        assert result.body["result"].get("sourcePath") != "canonical_company_cache"
        assert session.scalar(select(CandidateCompany).join(Company).where(Company.name == "Stale Civic AI Labs")) is None


class FakePlannerConnector:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(text=json.dumps(self.payload), provider="mock", model="mock")


class FakeTheirStackClient:
    def __init__(self, companies: list[dict[str, Any]]) -> None:
        self.companies = companies
        self.requests: list[TheirStackCompanySearchRequest] = []

    def search_companies(self, request: TheirStackCompanySearchRequest) -> TheirStackCompanySearchResult:
        self.requests.append(request)
        return TheirStackCompanySearchResult(
            status="completed",
            companies=tuple(self.companies),
            diagnostics=TheirStackCompanySearchDiagnostics(
                enabled=True,
                requested_pages=request.max_pages or 1,
                fetched_pages=1,
                raw_company_count=len(self.companies),
                request_shape=request.sanitized_shape(),
            ),
        )


def theirstack_payload() -> dict[str, Any]:
    return {
        "id": "company_123",
        "name": "Hightouch",
        "domain": "hightouch.com",
        "website_url": "https://hightouch.com",
        "linkedin_url": "https://www.linkedin.com/company/hightouch",
        "description": "Customer data platform.",
        "industry": "Data",
        "num_jobs_found": 42,
        "jobs_found": [{"url": "https://job-boards.greenhouse.io/hightouch/jobs/123"}],
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
                "headline": "AI product engineering leader",
                "summary": "Builds civic technology and AI systems.",
                "profileStatus": "draft",
            },
            hostname="rebekahalove.dev",
        )
        session.commit()
    return engine


def seeded_profile(session: Session):
    candidate_profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "rebekah-love"))
    assert candidate_profile is not None
    return candidate_profile


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
        theirstack_company_search_limit=25,
        theirstack_company_search_max_pages=1,
    )
