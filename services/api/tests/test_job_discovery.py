from __future__ import annotations

import json
import logging
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import jobops_api.command_center as command_center_module
from jobops_api.db.models import Base, CandidateCompany, CandidateSavedJob, Company, JobPosting
from jobops_api.db.seed_profile import seed_public_profile
from jobops_api.model_connector import ModelResponse
from jobops_api.job_discovery import (
    JobDiscoveryRequest,
    JobDiscoveryServiceResult,
    list_jobs,
    run_job_discovery,
)
from jobops_api.job_discovery.models import (
    JobSearchRequest,
    LiveJobSourceResult,
    ProviderSearchOutcome,
)
from jobops_api.job_discovery.providers.adzuna import build_adzuna_request, normalize_adzuna_result
from jobops_api.job_discovery.providers.greenhouse import normalize_greenhouse_result
from jobops_api.job_discovery.providers.registry import resolve_job_discovery_providers
from jobops_api.job_discovery.provider_utils import infer_location_query
from jobops_api.job_discovery.service import (
    build_provider_job_search_queries,
    infer_user_constraint_terms,
    infer_job_search_role_queries,
    save_live_job_source_results,
)
from jobops_api.settings import Settings


def test_job_discovery_creates_global_jobs_and_profile_links(tmp_path: Path) -> None:
    engine = create_seeded_engine()

    with Session(engine) as session:
        result = run_job_discovery(
            JobDiscoveryRequest(
                latest_user_message="Find me some jobs to apply to.",
                candidate_profile_slug="rebekah-love",
            ),
            db_session=session,
            settings=make_settings(tmp_path),
        )

        assert result.status_code == 200
        assert result.body["ok"] is True
        assert result.body["result"]["savedCount"] == 2
        assert result.body["result"]["createdGlobalJobCount"] == 2
        assert len(session.scalars(select(JobPosting)).all()) == 2
        assert len(session.scalars(select(CandidateSavedJob)).all()) == 2
        assert len(session.scalars(select(Company)).all()) == 2
        assert len(session.scalars(select(CandidateCompany)).all()) == 2
        assert all(job.company_id is not None for job in session.scalars(select(JobPosting)).all())

        saved_link = session.scalars(select(CandidateSavedJob).order_by(CandidateSavedJob.added_at.asc())).first()
        assert saved_link is not None
        assert saved_link.added_at is not None
        assert saved_link.status == "saved"
        assert saved_link.fit_summary
        assert any(job.posting_date is not None for job in session.scalars(select(JobPosting)).all())


def test_job_discovery_rediscovery_reuses_global_job_and_preserves_added_at(tmp_path: Path) -> None:
    engine = create_seeded_engine()

    with Session(engine) as session:
        first = run_job_discovery(
            JobDiscoveryRequest(latest_user_message="Find applied AI engineer jobs.", candidate_profile_slug="rebekah-love"),
            db_session=session,
            settings=make_settings(tmp_path),
        )
        assert first.status_code == 200
        first_links = list(session.scalars(select(CandidateSavedJob).order_by(CandidateSavedJob.id.asc())))
        first_added_at = {link.job.normalized_url: link.added_at for link in first_links}

        second = run_job_discovery(
            JobDiscoveryRequest(latest_user_message="Find applied AI engineer jobs again.", candidate_profile_slug="rebekah-love"),
            db_session=session,
            settings=make_settings(tmp_path),
        )

        assert second.status_code == 200
        assert second.body["result"]["savedCount"] == 0
        assert second.body["result"]["updatedExistingCount"] == 0
        assert second.body["result"]["duplicateCount"] == 2
        assert second.body["result"]["providerResultCount"] == 2
        assert second.body["result"]["modelSelectedCount"] == 0
        assert second.body["result"]["currentSavedJobCount"] == 2
        assert second.body["result"]["excludedJobUrlCount"] == 2
        assert "already in your Jobs list" in second.body["result"]["assistantMessage"]
        assert len(session.scalars(select(JobPosting)).all()) == 2
        assert len(session.scalars(select(CandidateSavedJob)).all()) == 2
        for link in session.scalars(select(CandidateSavedJob)).all():
            assert link.added_at == first_added_at[link.job.normalized_url]


def test_same_global_job_can_be_saved_by_different_profiles(tmp_path: Path) -> None:
    engine = create_seeded_engine(include_second_profile=True)

    with Session(engine) as session:
        for slug in ["rebekah-love", "alex-love"]:
            result = run_job_discovery(
                JobDiscoveryRequest(latest_user_message="Find remote AI platform roles.", candidate_profile_slug=slug),
                db_session=session,
                settings=make_settings(tmp_path),
            )
            assert result.status_code == 200

        jobs = session.scalars(select(JobPosting)).all()
        links = session.scalars(select(CandidateSavedJob)).all()

        assert len(jobs) == 2
        assert len(links) == 4
        assert len({link.candidate_profile_id for link in links}) == 2
        assert len({link.job_id for link in links}) == 2


def test_saved_job_link_fields_are_profile_specific_and_list_is_scoped() -> None:
    engine = create_seeded_engine(include_second_profile=True)
    with Session(engine) as session:
        profiles = {profile.slug: profile for profile in session.scalars(select(command_center_module.CandidateProfile)).all()}
        source_results = [
            LiveJobSourceResult(
                title="Applied AI Engineer",
                company_name="Example Civic",
                job_url="https://jobs.example.test/example-civic/applied-ai",
                source_provider="test_provider",
                provenance="provider_result",
                fit_summary="Matches applied AI for this profile.",
            )
        ]
        first = save_live_job_source_results(
            session,
            candidate_profile=profiles["rebekah-love"],
            discovery_query="Find jobs",
            source_results=source_results,
            search_queries_used=["Applied AI Engineer"],
            provider="test_provider",
            verify_urls=False,
        )
        second = save_live_job_source_results(
            session,
            candidate_profile=profiles["alex-love"],
            discovery_query="Find jobs",
            source_results=source_results,
            search_queries_used=["Applied AI Engineer"],
            provider="test_provider",
            verify_urls=False,
        )
        first.saved_links[0].user_notes = "Private first-user note"
        first.saved_links[0].status = "review"
        second.saved_links[0].user_notes = "Private second-user note"
        session.commit()

        first_payload = list_jobs(session=session, auth=SimpleNamespace(candidate_profile=profiles["rebekah-love"]))
        second_payload = list_jobs(session=session, auth=SimpleNamespace(candidate_profile=profiles["alex-love"]))

    assert len(first_payload) == 1
    assert len(second_payload) == 1
    assert first_payload[0]["job_id"] == second_payload[0]["job_id"]
    assert first_payload[0]["user_notes"] == "Private first-user note"
    assert first_payload[0]["status"] == "review"
    assert second_payload[0]["user_notes"] == "Private second-user note"
    assert "Private second-user note" not in json.dumps(first_payload)


def test_job_discovery_requires_reliable_url_and_allows_null_posting_date() -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        result = save_live_job_source_results(
            session,
            candidate_profile=profile,
            discovery_query="Find jobs",
            source_results=[
                LiveJobSourceResult(
                    title="No URL Role",
                    company_name="Example Civic",
                    job_url="",
                    source_provider="test_provider",
                    provenance="provider_result",
                ),
                LiveJobSourceResult(
                    title="Backend AI Engineer",
                    company_name="Example Civic",
                    job_url="https://jobs.example.test/example-civic/backend-ai",
                    source_provider="test_provider",
                    provenance="provider_result",
                    posting_date=None,
                ),
            ],
            search_queries_used=["Backend AI Engineer"],
            provider="test_provider",
            verify_urls=False,
        )

        assert [link.job.title for link in result.saved_links] == ["Backend AI Engineer"]
        assert result.saved_links[0].job.posting_date is None
        assert result.skipped[0].reason_code == "missing_required_url"


def test_provider_queries_use_explicit_targets_before_profile_inference() -> None:
    queries = infer_job_search_role_queries(
        "Find me jobs to apply to.",
        target_context={"target_role_titles": ["AI Product Engineer", "Developer Tools Engineer"]},
        private_profile_context={
            "profile_basics": {
                "headline": "Applied AI Systems Engineer | RAG, LLM Evaluation & Production AI Platforms",
            },
            "summary": "Strong fit for applied AI and data-intensive product roles.",
        },
    )

    assert queries[:2] == ["AI Product Engineer", "Developer Tools Engineer"]
    assert "Applied AI Engineer" not in queries


def test_provider_queries_do_not_rewrite_profile_applied_ai_phrase_to_target_title() -> None:
    request = JobDiscoveryRequest(latest_user_message="please find some jobs for me to apply to", candidate_profile_slug="rebekah-love")
    queries = build_provider_job_search_queries(
        request,
        current_saved_companies=[],
        target_context={},
        private_profile_context={
            "profile_basics": {
                "headline": "Applied AI Systems Engineer | RAG, LLM Evaluation & Production AI Platforms",
                "summary": "Strong fit for applied AI and forward-deployed engineering.",
            },
            "targets": {},
        },
    )

    assert queries[0] == "Applied AI Systems Engineer"
    assert "Applied AI Engineer" not in queries


def test_provider_queries_support_non_technical_profile_roles() -> None:
    queries = infer_job_search_role_queries(
        "please find some jobs for me to apply to",
        target_context={},
        private_profile_context={
            "profile_basics": {
                "headline": "Museum Collections Manager | Archives and Public Programming",
            },
            "targets": {},
        },
    )

    assert queries[0] == "Museum Collections Manager"
    assert "AI Engineer" not in queries
    assert "Machine Learning Engineer" not in queries


def test_provider_queries_without_profile_do_not_default_to_ai_roles() -> None:
    queries = infer_job_search_role_queries(
        "please find some jobs for me to apply to",
        target_context={},
        private_profile_context={},
    )

    assert queries == ["jobs"]


def test_provider_registry_parses_multiple_providers() -> None:
    providers = resolve_job_discovery_providers(("adzuna", "greenhouse", "ashby", "mock"))

    assert [provider.provider_name for provider in providers] == ["adzuna", "greenhouse", "ashby", "mock"]
    assert [provider.provider_type for provider in providers] == ["broad_search", "ats_board", "ats_board", "mock"]


def test_provider_modules_do_not_import_service_module() -> None:
    provider_dir = Path(command_center_module.__file__).parent / "job_discovery" / "providers"
    for module_name in ("adzuna.py", "greenhouse.py", "mock.py", "ashby.py", "base.py", "registry.py"):
        source = (provider_dir / module_name).read_text(encoding="utf-8")
        assert "..service" not in source
        assert "job_discovery.service" not in source


def test_provider_registry_returns_provider_classes() -> None:
    from jobops_api.job_discovery.providers.adzuna import AdzunaJobDiscoveryProvider
    from jobops_api.job_discovery.providers.ashby import AshbyJobDiscoveryProvider
    from jobops_api.job_discovery.providers.greenhouse import GreenhouseJobDiscoveryProvider
    from jobops_api.job_discovery.providers.mock import MockJobDiscoveryProvider

    providers = resolve_job_discovery_providers(("mock", "adzuna", "greenhouse", "ashby"))

    assert isinstance(providers[0], MockJobDiscoveryProvider)
    assert isinstance(providers[1], AdzunaJobDiscoveryProvider)
    assert isinstance(providers[2], GreenhouseJobDiscoveryProvider)
    assert isinstance(providers[3], AshbyJobDiscoveryProvider)
    assert providers[1].provider_type == "broad_search"
    assert providers[2].provider_type == "ats_board"


def test_selection_serializes_normalized_candidates_without_provider_class() -> None:
    from jobops_api.job_discovery.models import CandidatePoolEntry
    from jobops_api.job_discovery.selection import serialize_candidate_pool_entry

    entry = CandidatePoolEntry(
        candidate_id="J001",
        result=LiveJobSourceResult(
            title="AI Platform Engineer",
            company_name="Example Co",
            job_url="https://example.com/jobs/ai-platform",
            source_provider="adzuna",
            provider_type="broad_search",
            source_result_id="adzuna-1",
            description_excerpt="Build LLM platform workflows.",
        ),
        rough_score=12,
        flags=("posting_date_unknown",),
    )

    payload = serialize_candidate_pool_entry(entry)

    assert payload["candidateId"] == "J001"
    assert payload["providerName"] == "adzuna"
    assert payload["providerType"] == "broad_search"
    assert payload["title"] == "AI Platform Engineer"


def test_provider_registry_rejects_unknown_provider() -> None:
    try:
        resolve_job_discovery_providers(("adzuna", "unknown-provider"))
    except Exception as error:
        assert "Unknown job discovery provider" in str(error)
    else:
        raise AssertionError("Expected unknown provider to fail")


def test_adzuna_provider_builds_params_and_normalizes_results(tmp_path: Path) -> None:
    settings = make_settings(
        tmp_path,
        model_provider="mock",
        job_discovery_source="none",
        job_discovery_providers=("adzuna",),
        adzuna_app_id="app-id",
        adzuna_app_key="app-key",
        adzuna_country="us",
    )
    request = JobSearchRequest(
        latest_user_message="Find remote applied AI jobs but avoid gambling, night shift, and commission-only sales",
        search_queries=["Applied AI Engineer remote"],
        results_per_provider=12,
        current_saved_companies=[],
        target_context={},
        private_profile_context={},
        user_constraints=["gambling", "night shift", "commission-only sales"],
    )

    url, params = build_adzuna_request(settings, request, query="Applied AI Engineer remote")
    result = normalize_adzuna_result(
        {
            "id": "adz-1",
            "title": "Applied AI Engineer",
            "company": {"display_name": "Provider Co"},
            "redirect_url": "https://www.adzuna.com/land/ad/1",
            "location": {"display_name": "Remote US"},
            "description": "<p>Build LLM tools</p>",
            "created": "2026-05-20T10:30:00Z",
            "salary_min": 150000,
            "salary_max": 180000,
            "contract_time": "full_time",
        },
        query="Applied AI Engineer remote",
        settings=settings,
    )

    assert url == "https://api.adzuna.com/v1/api/jobs/us/search/1"
    assert params["app_id"] == "app-id"
    assert params["app_key"] == "app-key"
    assert params["what"] == "Applied AI Engineer remote"
    assert params["results_per_page"] == 12
    assert params["what_exclude"] == "gambling night shift commission-only sales"
    assert result is not None
    assert result.source_provider == "adzuna"
    assert result.provider_type == "broad_search"
    assert result.job_url == "https://www.adzuna.com/land/ad/1"
    assert result.posting_date is not None
    assert result.source_updated_at is not None


def test_job_discovery_constraint_terms_are_not_limited_to_fixed_industries() -> None:
    constraints = infer_user_constraint_terms(
        "Find sales roles, but avoid night shift, commission-only work, and booze brands.",
        target_context={"constraints": ["No oil and gas", "avoid unpaid internships"]},
        private_profile_context={"preferences": {"excluded_industries": ["fast fashion"]}},
    )

    assert "night shift" in constraints
    assert "commission-only" in constraints
    assert "booze brands" in constraints
    assert "oil" in constraints
    assert "gas" in constraints
    assert "unpaid internships" in constraints
    assert "fast fashion" in constraints


def test_location_query_uses_explicit_command_location() -> None:
    location = infer_location_query(
        "Find product manager roles near Portland, OR for climate orgs",
        target_context={"preferred_locations": ["Remote US"]},
        private_profile_context={},
    )

    assert location == "Portland, OR"


def test_location_query_uses_saved_preferred_location_without_command_location() -> None:
    location = infer_location_query(
        "Find product manager roles",
        target_context={"preferred_locations": ["Chicago, IL", "Denver, CO"]},
        private_profile_context={},
    )

    assert location == "Chicago, IL"


def test_location_query_remote_command_does_not_send_restrictive_location() -> None:
    location = infer_location_query(
        "Find remote product manager roles",
        target_context={"preferred_locations": ["Chicago, IL"]},
        private_profile_context={},
    )

    assert location is None


def test_location_query_returns_none_without_command_or_profile_location() -> None:
    assert infer_location_query("Find product manager roles", target_context={}, private_profile_context={}) is None


def test_location_query_has_no_hard_coded_personal_city_behavior() -> None:
    assert infer_location_query("Find product manager roles", target_context={}, private_profile_context={}) is None
    assert infer_location_query("Find product manager roles", target_context={"notes": "Louisville"}, private_profile_context={}) is None
    assert infer_location_query("Find product manager roles", target_context={"notes": "NYC"}, private_profile_context={}) is None


def test_greenhouse_provider_normalizes_board_jobs() -> None:
    request = JobSearchRequest(
        latest_user_message="Find platform jobs",
        search_queries=["AI Platform Engineer"],
        results_per_provider=20,
        current_saved_companies=[{"name": "Example Civic", "careers_url": "https://boards.greenhouse.io/examplecivic"}],
        target_context={},
        private_profile_context={},
        user_constraints=[],
    )

    result = normalize_greenhouse_result(
        {
            "id": 123,
            "title": "AI Platform Engineer",
            "absolute_url": "https://boards.greenhouse.io/examplecivic/jobs/123",
            "updated_at": "2026-05-21T12:00:00-04:00",
            "location": {"name": "Remote"},
            "content": "<p>Own retrieval and evaluation systems.</p>",
        },
        board_token="examplecivic",
        request=request,
    )

    assert result is not None
    assert result.source_provider == "greenhouse"
    assert result.provider_type == "ats_board"
    assert result.source_result_id == "examplecivic:123"
    assert result.company_name == "Example Civic"
    assert result.job_url == "https://boards.greenhouse.io/examplecivic/jobs/123"
    assert result.description_excerpt == "Own retrieval and evaluation systems."
    assert result.source_updated_at is not None
    assert result.posting_date is None


def test_orchestration_runs_multiple_providers_and_dedupes(monkeypatch, tmp_path: Path) -> None:
    class FakeResponse:
        status = 200
        headers = {"content-type": "application/json"}

        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, *_args):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        url = request.full_url
        if "adzuna" in url:
            return FakeResponse(
                {
                    "results": [
                        {
                            "id": "adz-1",
                            "title": "Applied AI Engineer",
                            "company": {"display_name": "Example Civic"},
                            "redirect_url": "https://jobs.example.com/shared",
                            "location": {"display_name": "Remote"},
                            "description": "Applied AI role",
                        }
                    ]
                }
            )
        return FakeResponse(
            {
                "jobs": [
                    {
                        "id": 123,
                        "title": "Applied AI Engineer",
                        "absolute_url": "https://jobs.example.com/shared",
                        "location": {"name": "Remote"},
                        "content": "Applied AI role",
                    }
                ]
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    engine = create_seeded_engine()
    settings = make_settings(
        tmp_path,
        model_provider="mock",
        job_discovery_source="none",
        job_discovery_providers=("adzuna", "greenhouse"),
        adzuna_app_id="app-id",
        adzuna_app_key="app-key",
        greenhouse_board_tokens=("examplecivic",),
    )

    with Session(engine) as session:
        result = run_job_discovery(
            JobDiscoveryRequest(latest_user_message="Find applied AI jobs.", candidate_profile_slug="rebekah-love"),
            db_session=session,
            settings=settings,
        )

        assert result.status_code == 200
        assert result.body["result"]["configuredProviders"] == ["adzuna", "greenhouse"]
        assert result.body["result"]["providerResultCount"] == 2
        assert result.body["result"]["candidateCountAfterDedupe"] == 1
        assert result.body["result"]["savedCount"] == 1
        assert len(result.body["result"]["providerDiagnostics"]) == 2
        assert [item["providerName"] for item in result.body["result"]["providerDiagnostics"]] == ["adzuna", "greenhouse"]
        saved_job = session.scalar(select(JobPosting))
        assert saved_job is not None
        assert saved_job.source_provider == "adzuna"



def test_model_selection_saves_only_selected_provider_candidates(monkeypatch, tmp_path: Path) -> None:
    captured_request = None

    class FakeResponse:
        status = 200
        headers = {"content-type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, *_args):
            return json.dumps(
                {
                    "results": [
                        {
                            "id": "adz-1",
                            "title": "Generic Software Engineer",
                            "company": {"display_name": "Generic Co"},
                            "redirect_url": "https://jobs.example.test/generic",
                            "description": "Backend services.",
                        },
                        {
                            "id": "adz-2",
                            "title": "AI Platform Engineer",
                            "company": {"display_name": "Aligned AI"},
                            "redirect_url": "https://jobs.example.test/ai-platform",
                            "description": "RAG evaluation and AI workflow automation.",
                        },
                    ]
                }
            ).encode("utf-8")

    class FakeConnector:
        def generate(self, request):
            nonlocal captured_request
            captured_request = request
            payload = json.loads(request.messages[-1].content)
            selected_candidate = next(
                item for item in payload["candidate_jobs"] if item["title"] == "AI Platform Engineer"
            )
            skipped_candidate = next(
                item for item in payload["candidate_jobs"] if item["title"] == "Generic Software Engineer"
            )
            return ModelResponse(
                text=json.dumps(
                    {
                        "assistantMessage": "Selected the strongest provider-backed AI role.",
                        "selectedJobs": [
                            {
                                "candidateId": selected_candidate["candidateId"],
                                "fitSummary": "Direct fit for RAG evaluation and AI platform work.",
                                "rank": 1,
                                "selectionReason": "Provider candidate is more aligned than the generic backend role.",
                                "concerns": [],
                            },
                            {
                                "candidateId": "J999",
                                "fitSummary": "Should be ignored.",
                                "rank": 2,
                                "selectionReason": "Invalid candidate.",
                                "concerns": [],
                            },
                        ],
                        "skippedCandidateNotes": [{"candidateId": skipped_candidate["candidateId"], "reason": "Too generic."}],
                        "clarifyingQuestions": [],
                    }
                ),
                provider="fake",
                model="fake-model",
            )

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: FakeResponse())
    engine = create_seeded_engine()
    settings = make_settings(
        tmp_path,
        model_provider="gemini",
        job_discovery_source="none",
        job_discovery_providers=("adzuna",),
        adzuna_app_id="app-id",
        adzuna_app_key="app-key",
    )

    with Session(engine) as session:
        result = run_job_discovery(
            JobDiscoveryRequest(latest_user_message="Find AI platform jobs.", candidate_profile_slug="rebekah-love"),
            connector=FakeConnector(),
            db_session=session,
            settings=settings,
        )

        assert result.status_code == 200
        assert result.body["result"]["candidateCountSentToModel"] == 2
        assert result.body["result"]["modelSelectedCount"] == 1
        assert result.body["result"]["selectedCandidateIds"]
        assert result.body["result"]["invalidSelectedCandidateIds"] == ["J999"]
        assert result.body["result"]["savedCount"] == 1
        saved_job = session.scalar(select(JobPosting))
        assert saved_job is not None
        assert saved_job.title == "AI Platform Engineer"
        assert saved_job.company_name == "Aligned AI"
        assert saved_job.job_url == "https://jobs.example.test/ai-platform"
        saved_link = session.scalar(select(CandidateSavedJob))
        assert saved_link is not None
        assert saved_link.fit_summary == "Direct fit for RAG evaluation and AI platform work."
        assert captured_request is not None
        request_payload = json.loads(captured_request.messages[-1].content)
        assert len(request_payload["candidate_jobs"]) == 2
        assert any(item["title"] == "AI Platform Engineer" for item in request_payload["candidate_jobs"])


def test_model_selection_validation_failure_logs_visible_payload(monkeypatch, tmp_path: Path, caplog) -> None:
    class FakeResponse:
        status = 200
        headers = {"content-type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, *_args):
            return json.dumps(
                {
                    "results": [
                        {
                            "id": "adz-1",
                            "title": "AI Platform Engineer",
                            "company": {"display_name": "Aligned AI"},
                            "redirect_url": "https://jobs.example.test/ai-platform",
                            "description": "RAG evaluation and AI workflow automation.",
                        }
                    ]
                }
            ).encode("utf-8")

    class BadJsonConnector:
        def generate(self, request):
            return ModelResponse(text="not json", provider="fake", model="fake-model", finish_reason="stop")

    logging.disable(logging.NOTSET)
    selection_logger = logging.getLogger("jobops_api.job_discovery.selection")
    selection_logger.disabled = False
    selection_logger.propagate = True
    caplog.set_level(logging.WARNING, logger="jobops_api.job_discovery.selection")
    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: FakeResponse())
    engine = create_seeded_engine()
    settings = make_settings(
        tmp_path,
        model_provider="gemini",
        job_discovery_source="none",
        job_discovery_providers=("adzuna",),
        adzuna_app_id="app-id",
        adzuna_app_key="app-key",
    )

    with Session(engine) as session:
        result = run_job_discovery(
            JobDiscoveryRequest(latest_user_message="Find AI platform jobs.", candidate_profile_slug="rebekah-love"),
            connector=BadJsonConnector(),
            db_session=session,
            settings=settings,
        )

        assert result.status_code == 502
        assert result.body["code"] == "job_candidate_selection_validation_failed"
        assert "Job candidate selection model output validation failed:" in caplog.text
        assert '"provider": "fake"' in caplog.text
        assert '"responsePreview": "not json"' in caplog.text


def test_model_selection_truncation_retries_with_compact_payload(monkeypatch, tmp_path: Path) -> None:
    calls = []

    class FakeResponse:
        status = 200
        headers = {"content-type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, *_args):
            return json.dumps(
                {
                    "results": [
                        {
                            "id": "adz-1",
                            "title": "AI Platform Engineer",
                            "company": {"display_name": "Aligned AI"},
                            "redirect_url": "https://jobs.example.test/ai-platform",
                            "description": "RAG evaluation and AI workflow automation.",
                        }
                    ]
                }
            ).encode("utf-8")

    class TruncatingConnector:
        def generate(self, request):
            calls.append(request)
            if len(calls) == 1:
                return ModelResponse(
                    text='{"assistantMessage":"too long","selectedJobs":[{"candidateId":"J001"',
                    provider="fake",
                    model="fake-model",
                    finish_reason="MAX_TOKENS",
                )
            payload = json.loads(request.messages[-1].content)
            assert payload["compact_retry"] is True
            assert "jobUrl" not in payload["candidate_jobs"][0]
            return ModelResponse(
                text=json.dumps(
                    {
                        "assistantMessage": "Selected one match.",
                        "selectedJobs": [
                            {
                                "candidateId": "J001",
                                "fitSummary": "Strong AI platform fit.",
                                "rank": 1,
                                "selectionReason": "Matches RAG and platform work.",
                                "concerns": [],
                            }
                        ],
                        "skippedCandidateNotes": [],
                        "clarifyingQuestions": [],
                    }
                ),
                provider="fake",
                model="fake-model",
                finish_reason="stop",
            )

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: FakeResponse())
    engine = create_seeded_engine()
    settings = make_settings(
        tmp_path,
        model_provider="gemini",
        job_discovery_source="none",
        job_discovery_providers=("adzuna",),
        adzuna_app_id="app-id",
        adzuna_app_key="app-key",
    )

    with Session(engine) as session:
        result = run_job_discovery(
            JobDiscoveryRequest(latest_user_message="Find AI platform jobs.", candidate_profile_slug="rebekah-love"),
            connector=TruncatingConnector(),
            db_session=session,
            settings=settings,
        )

        assert result.status_code == 200
        assert len(calls) == 2
        assert result.body["result"]["savedCount"] == 1
        assert result.body["result"]["selectedCandidateIds"] == ["J001"]


def test_unconfigured_provider_returns_structured_error(tmp_path: Path) -> None:
    engine = create_seeded_engine()
    settings = make_settings(
        tmp_path,
        model_provider="mock",
        job_discovery_source="none",
        job_discovery_providers=("adzuna",),
        adzuna_app_id=None,
        adzuna_app_key=None,
    )

    with Session(engine) as session:
        result = run_job_discovery(
            JobDiscoveryRequest(latest_user_message="Find applied AI jobs.", candidate_profile_slug="rebekah-love"),
            db_session=session,
            settings=settings,
        )

        assert result.status_code == 502
        assert result.body["code"] == "live_job_discovery_provider_failed"
        assert result.body["providerDiagnostics"][0]["configured"] is False
        assert len(session.scalars(select(JobPosting)).all()) == 0


def test_provider_zero_results_are_logged(monkeypatch, tmp_path: Path, caplog) -> None:
    class FakeResponse:
        status = 200
        headers = {"content-type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, *_args):
            return json.dumps({"results": []}).encode("utf-8")

    caplog.set_level(logging.INFO, logger="jobops_api.job_discovery")
    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: FakeResponse())
    engine = create_seeded_engine()
    settings = make_settings(
        tmp_path,
        model_provider="mock",
        job_discovery_source="none",
        job_discovery_providers=("adzuna",),
        adzuna_app_id="app-id",
        adzuna_app_key="app-key",
    )

    with Session(engine) as session:
        result = run_job_discovery(
            JobDiscoveryRequest(latest_user_message="Find applied AI jobs.", candidate_profile_slug="rebekah-love"),
            db_session=session,
            settings=settings,
        )

        assert result.status_code == 200
        assert result.body["result"]["providerResultCount"] == 0
        assert result.body["result"]["providerDiagnostics"][0]["providerName"] == "adzuna"
        assert result.body["result"]["providerDiagnostics"][0]["resultCount"] == 0
        assert result.body["result"]["providerDiagnostics"][0]["attempted"] is True


def test_provider_http_errors_are_logged(monkeypatch, tmp_path: Path, caplog) -> None:
    caplog.set_level(logging.INFO, logger="jobops_api.job_discovery")

    def fake_urlopen(_request, timeout):
        raise urllib.error.HTTPError(
            url="https://api.adzuna.com/v1/api/jobs/us/search/1",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    engine = create_seeded_engine()
    settings = make_settings(
        tmp_path,
        model_provider="mock",
        job_discovery_source="none",
        job_discovery_providers=("adzuna",),
        adzuna_app_id="app-id",
        adzuna_app_key="app-key",
    )

    with Session(engine) as session:
        result = run_job_discovery(
            JobDiscoveryRequest(latest_user_message="Find applied AI jobs.", candidate_profile_slug="rebekah-love"),
            db_session=session,
            settings=settings,
        )

        assert result.status_code == 502
        assert result.body["code"] == "live_job_discovery_provider_failed"
        assert result.body["providerDiagnostics"][0]["providerName"] == "adzuna"
        assert result.body["providerDiagnostics"][0]["error"] == "Adzuna request failed with HTTP 401."


def test_partial_provider_failure_can_still_save_results(monkeypatch, tmp_path: Path) -> None:
    class FakeResponse:
        status = 200
        headers = {"content-type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, *_args):
            return json.dumps(
                {
                    "jobs": [
                        {
                            "id": 123,
                            "title": "AI Platform Engineer",
                            "absolute_url": "https://boards.greenhouse.io/examplecivic/jobs/123",
                            "location": {"name": "Remote"},
                            "content": "AI platform role",
                        }
                    ]
                }
            ).encode("utf-8")

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: FakeResponse())
    engine = create_seeded_engine()
    settings = make_settings(
        tmp_path,
        model_provider="mock",
        job_discovery_source="none",
        job_discovery_providers=("adzuna", "greenhouse"),
        allow_partial=True,
        adzuna_app_id=None,
        adzuna_app_key=None,
        greenhouse_board_tokens=("examplecivic",),
    )

    with Session(engine) as session:
        result = run_job_discovery(
            JobDiscoveryRequest(latest_user_message="Find AI platform jobs.", candidate_profile_slug="rebekah-love"),
            db_session=session,
            settings=settings,
        )

        assert result.status_code == 200
        assert result.body["result"]["savedCount"] == 1
        assert result.body["result"]["providerDiagnostics"][0]["configured"] is False
        assert result.body["result"]["providerDiagnostics"][1]["resultCount"] == 1



def test_404_job_url_is_skipped(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", hdrs=None, fp=None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        result = save_live_job_source_results(
            session,
            candidate_profile=profile,
            discovery_query="Find jobs",
            source_results=[
                LiveJobSourceResult(
                    title="Applied AI Engineer",
                    company_name="Closed Co",
                    job_url="https://closed.example/jobs/old",
                    source_provider="test_provider",
                    provenance="provider_result",
                )
            ],
            search_queries_used=["Applied AI Engineer jobs"],
            provider="test_provider",
            verify_urls=True,
        )

        assert result.saved_links == []
        assert result.skipped[0].reason_code == "expired_or_closed"
        assert len(session.scalars(select(JobPosting)).all()) == 0


def test_provider_result_can_be_saved_with_provenance_without_fetch() -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        result = save_live_job_source_results(
            session,
            candidate_profile=profile,
            discovery_query="Find jobs",
            source_results=[
                LiveJobSourceResult(
                    title="Applied AI Engineer",
                    company_name="Provider Co",
                    job_url="https://provider.example/jobs/applied-ai",
                    source_provider="test_provider",
                    source_result_id="job-123",
                    source_query="Applied AI Engineer jobs",
                    source_url="https://provider.example/jobs/applied-ai",
                    provenance="provider_result",
                    posting_date=None,
                    fit_summary="Provider-backed result.",
                )
            ],
            search_queries_used=["Applied AI Engineer jobs"],
            provider="test_provider",
            verify_urls=False,
        )

        assert len(result.saved_links) == 1
        job = result.saved_links[0].job
        assert job.provenance == "provider_result"
        assert job.source_provider == "test_provider"
        assert job.source_result_id == "job-123"
        assert job.url_verification_status == "provider_unverified"
        assert job.posting_date is None


def test_user_provided_valid_job_url_can_be_saved_when_fetched(monkeypatch, tmp_path: Path) -> None:
    class FakeResponse:
        status = 200
        headers = {"content-type": "text/html; charset=utf-8"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def geturl(self):
            return "https://company.example/jobs/live"

        def read(self, _size):
            return b"<html><title>Live Role</title><body>Live Role at Company Example is open for applications.</body></html>"

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: FakeResponse())
    engine = create_seeded_engine()
    with Session(engine) as session:
        result = run_job_discovery(
            JobDiscoveryRequest(
                latest_user_message="Save this job https://company.example/jobs/live",
                candidate_profile_slug="rebekah-love",
            ),
            db_session=session,
            settings=make_settings(tmp_path, model_provider="gemini", job_discovery_source="none"),
        )

        assert result.status_code == 200
        assert result.body["result"]["savedCount"] == 1
        saved_job = session.scalar(select(JobPosting))
        assert saved_job is not None
        assert saved_job.provenance == "user_url"
        assert saved_job.url_verification_status == "verified"
        assert saved_job.posting_date is None


def test_command_center_job_discovery_returns_saved_job_payload(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(command_center_module, "load_settings", lambda: make_settings(tmp_path))
    engine = create_seeded_engine()

    with Session(engine) as session:
        response = command_center_module.execute_command_center_command(
            command_center_module.CommandCenterCommandRequest(
                command="Find me some jobs to apply to.",
                active_workspace="jobs",
            ),
            session=session,
        )

        assert response.actions[0].type == "job_discovery"
        assert response.actions[0].status == "completed"
        assert response.target_workspace == "jobs"
        assert response.result_payload is not None
        assert response.result_payload["jobDiscoveryMode"] == "mock"
        assert response.result_payload["providerResultCount"] == 2
        assert response.result_payload["jobs"][0]["job_url"].startswith(
            ("https://example-mission-org.example.test/", "https://sample-growth-co.example.test/")
        )
        assert response.result_payload["jobs"][0]["added_at"]
        assert len(session.scalars(select(JobPosting)).all()) == 2
        assert len(session.scalars(select(CandidateSavedJob)).all()) == 2


def test_job_discovery_returns_clear_error_when_live_source_not_configured(tmp_path: Path) -> None:
    engine = create_seeded_engine()
    settings = make_settings(tmp_path, model_provider="gemini", job_discovery_source="none")

    with Session(engine) as session:
        result = run_job_discovery(
            JobDiscoveryRequest(latest_user_message="Find some jobs for me to apply to.", candidate_profile_slug="rebekah-love"),
            db_session=session,
            settings=settings,
        )

        assert result.status_code == 503
        assert result.body["code"] == "live_job_discovery_not_configured"
        assert result.body["error"] == "Live job discovery is not configured. No jobs were saved."
        assert result.body["jobDiscoveryMode"] == "unavailable"
        assert result.body["providerResultCount"] == 0
        assert len(session.scalars(select(JobPosting)).all()) == 0


def test_command_center_job_discovery_passes_actual_chat_transcript(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(command_center_module, "load_settings", lambda: make_settings(tmp_path))
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        command_center_module,
        "run_command_router",
        lambda *args, **kwargs: SimpleNamespace(
            decision=command_center_module.CommandRouterOutput(
                actionType="job_discovery",
                confidence="high",
                targetWorkspace="jobs",
                reason="User asked for concrete job postings.",
            ),
            body={"ok": True},
            unavailable=False,
        ),
    )

    def fake_run_job_discovery(request: JobDiscoveryRequest, **kwargs) -> JobDiscoveryServiceResult:
        captured["client_context"] = request.client_context
        captured["latest_user_message"] = request.latest_user_message
        return JobDiscoveryServiceResult(
            status_code=200,
            body={
                "ok": True,
                "result": {
                    "assistantMessage": "No new jobs were saved.",
                    "jobs": [],
                    "updatedExistingJobs": [],
                    "skippedJobs": [],
                    "savedCount": 0,
                    "updatedExistingCount": 0,
                    "skippedJobCount": 0,
                    "createdGlobalJobCount": 0,
                    "updatedGlobalJobCount": 0,
                },
            },
        )

    monkeypatch.setattr(command_center_module, "run_job_discovery", fake_run_job_discovery)
    engine = create_seeded_engine()

    client_context = {
        "transcript": {
            "messages": [
                {"role": "user", "type": "message", "text": "avoid gambling and crypto"},
                {"role": "assistant", "type": "message", "text": "Got it."},
            ]
        }
    }
    with Session(engine) as session:
        response = command_center_module.execute_command_center_command(
            command_center_module.CommandCenterCommandRequest(
                command="Find me more applied AI jobs.",
                candidate_profile_slug="rebekah-love",
                active_workspace="jobs",
                clientContext=client_context,
            ),
            session=session,
        )

    assert response.actions[0].type == "job_discovery"
    assert captured["latest_user_message"] == "Find me more applied AI jobs."
    assert captured["client_context"] == client_context



def test_command_center_safe_action_log_metrics_are_counts_only() -> None:
    action = command_center_module.CommandCenterActionResult(
        type="job_discovery",
        status="completed",
        targetWorkspace="jobs",
        title="Discover jobs",
        summary="Done.",
        resultPayload={
            "savedCount": 1,
            "updatedExistingCount": 2,
            "skippedJobCount": 3,
            "currentSavedJobCount": 8,
            "excludedJobUrlCount": 8,
            "currentSavedCompanyCount": 44,
            "skippedReasonCounts": {"Job URL was not supported by fresh search grounding/source URLs.": 3},
            "modelRequest": {"messages": ["private prompt"]},
            "jobs": [{"title": "Private saved job"}],
        },
    )

    metrics = command_center_module.safe_action_log_metrics(action)

    assert metrics == {
        "type": "job_discovery",
        "status": "completed",
        "targetWorkspace": "jobs",
        "savedCount": 1,
        "updatedExistingCount": 2,
        "skippedJobCount": 3,
        "currentSavedJobCount": 8,
        "excludedJobUrlCount": 8,
        "currentSavedCompanyCount": 44,
        "skippedReasons": {"Job URL was not supported by fresh search grounding/source URLs.": 3},
    }


def create_seeded_engine(*, include_second_profile: bool = False):
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
        if include_second_profile:
            seed_public_profile(
                session,
                {
                    "slug": "alex-love",
                    "displayName": "Alex Love",
                    "headline": "AI platform candidate",
                    "summary": "Second private profile.",
                    "profileStatus": "draft",
                },
                hostname="alexlove.dev",
            )
        session.commit()

    return engine


def make_settings(
    repo_root: Path,
    *,
    model_provider: str = "mock",
    job_discovery_source: str = "mock",
    job_discovery_providers: tuple[str, ...] = (),
    allow_partial: bool = False,
    adzuna_app_id: str | None = None,
    adzuna_app_key: str | None = None,
    adzuna_country: str = "us",
    greenhouse_board_tokens: tuple[str, ...] = (),
) -> Settings:
    return Settings(
        app_env="test",
        cheap_model="mock-cheap",
        company_discovery_search_grounding_enabled=True,
        database_url=None,
        default_model="mock-default",
        gemini_api_key=None,
        model_provider=model_provider,
        job_discovery_source=job_discovery_source,
        job_discovery_providers=job_discovery_providers,
        job_discovery_allow_partial_provider_failures=allow_partial,
        job_discovery_results_per_provider=20,
        adzuna_app_id=adzuna_app_id,
        adzuna_app_key=adzuna_app_key,
        adzuna_country=adzuna_country,
        greenhouse_board_tokens=greenhouse_board_tokens,
        profile_intake_save_artifacts=False,
        profile_intake_save_raw_text=False,
        repo_root=repo_root,
    )
