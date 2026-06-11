from __future__ import annotations

import json
import logging
import urllib.error
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import jobops_api.command_center as command_center_module
import jobops_api.job_discovery.service as job_discovery_service_module
from jobops_api.db.models import Base, CandidateCompany, CandidateProfile, CandidateSavedJob, Company, JobPosting, JobSearchQueryRun, JobSearchRun
from jobops_api.db.seed_profile import seed_public_profile
from jobops_api.model_connector import ModelResponse
from jobops_api.job_discovery import (
    JobDiscoveryRequest,
    JobDiscoveryServiceResult,
    list_jobs,
    run_job_discovery,
)
from jobops_api.job_discovery.models import (
    JobSearchPlan,
    JobSearchRequest,
    LiveJobSourceResult,
    ProviderDiagnostic,
    ProviderSearchOutcome,
)
from jobops_api.job_discovery.planning import (
    apply_job_search_plan_guardrails,
    build_fallback_job_search_plan,
    build_job_search_planner_model_request,
    select_job_search_plan_with_model,
    validate_job_search_planner_output,
)
from jobops_api.job_discovery.providers.adzuna import build_adzuna_request, normalize_adzuna_result
from jobops_api.job_discovery.greenhouse_seed import upsert_greenhouse_companies_for_candidate
from jobops_api.job_discovery.providers.greenhouse import (
    canonical_greenhouse_jobs_api_url,
    normalize_greenhouse_result,
    parse_greenhouse_url,
    GreenhouseJobDiscoveryProvider,
)
from jobops_api.job_discovery.providers.registry import resolve_job_discovery_providers
from jobops_api.job_discovery.provider_utils import infer_location_query
from jobops_api.job_discovery.service import (
    build_provider_job_search_queries,
    build_provider_job_search_queries_from_plan,
    infer_user_constraint_terms,
    infer_job_search_role_queries,
    route_job_discovery_providers,
    run_configured_job_providers,
    save_live_job_source_results,
    should_tolerate_partial_company_board_errors,
)
from jobops_api.job_discovery.url_verification import source_result_verification
from jobops_api.settings import Settings


SKIP_LEGACY_LIVE_PROVIDER_DISCOVERY = pytest.mark.skip(
    reason="Branch 4 replaced candidate-facing live-provider discovery with DB-backed synced inventory."
)


def fake_job_search_planner_response(
    *,
    role_query: str = "AI Platform Engineer",
    locations: list[str] | None = None,
    requested_result_goal: int = 20,
) -> ModelResponse:
    return ModelResponse(
        text=json.dumps(
            {
                "searchPlan": {
                    "searchMode": "broad",
                    "roleQueries": [role_query],
                    "companyNames": [],
                    "locations": locations or [],
                    "remoteWorkModes": [],
                    "employmentTypes": [],
                    "salaryMin": None,
                    "includeTerms": [],
                    "excludeTerms": [],
                    "hardConstraints": [],
                    "softPreferences": [],
                    "providerStrategy": {
                        "useBroadSearch": True,
                        "useCompanyBoards": True,
                        "requestedResultGoal": requested_result_goal,
                        "maxProviderPages": 2,
                        "allowReplanning": True,
                    },
                    "rationale": "Fake planner response for tests.",
                }
            }
        ),
        provider="fake",
        model="fake-planner",
    )


@SKIP_LEGACY_LIVE_PROVIDER_DISCOVERY
def test_job_discovery_creates_global_jobs_and_profile_links(tmp_path: Path) -> None:
    engine = create_seeded_engine()

    with Session(engine) as session:
        result = run_job_discovery(
            JobDiscoveryRequest(
                latest_user_message="Find applied AI engineer jobs to apply to.",
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
        assert saved_link.status == "new"
        assert saved_link.fit_summary
        assert any(job.posting_date is not None for job in session.scalars(select(JobPosting)).all())


def test_job_search_run_status_is_scoped_to_authenticated_candidate() -> None:
    engine = create_seeded_engine(include_second_profile=True)

    with Session(engine) as session:
        owner = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "rebekah-love"))
        other = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "alex-love"))
        assert owner is not None
        assert other is not None
        run = JobSearchRun(
            candidate_profile_id=owner.id,
            command_text="find jobs",
            search_plan_json={},
            run_diagnostics_json={
                "userVisibleSummary": "I found jobs, but the best matches were already saved.",
                "userSummary": "I found jobs, but the best matches were already saved.",
                "planner": {
                    "rationale": "Search followed companies for applied AI roles.",
                    "fallbackUsed": False,
                    "recentSearchesUsedCount": 2,
                },
                "selection": {
                    "assistantMessage": "The model selected strong roles, but persistence found duplicates.",
                    "skippedCandidateNotes": [{"candidateId": "J002", "reason": "Too generic."}],
                    "clarifyingQuestions": [],
                },
                "replanning": {
                    "replansAttempted": 1,
                    "replanLimit": 1,
                    "replanningStatus": "attempted",
                    "replanningDecision": "triggered:zero_total_matches",
                    "replanReason": "zero_total_matches",
                    "replanReasons": ["zero_total_matches"],
                    "replanQueries": ["Applied AI Engineer"],
                },
            },
            provider_names=[],
            status="completed",
            total_provider_results=19,
            candidate_pool_count=10,
            candidate_count_after_dedupe=8,
            model_selected_count=3,
            saved_count=1,
            updated_existing_count=2,
            duplicate_count=4,
            skipped_count=5,
            provider_error_count=0,
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        payload = job_discovery_service_module.get_job_search_run_status(
            run.id,
            session=session,
            auth=SimpleNamespace(candidate_profile=owner),
        )
        assert payload["id"] == run.id
        assert payload["providerResultCount"] == 19
        assert payload["candidateCountAfterDedupe"] == 8
        assert payload["savedCount"] == 1
        assert payload["message"] == "I found jobs, but the best matches were already saved."
        assert payload["userVisibleSummary"] == "I found jobs, but the best matches were already saved."
        assert payload["plannerRationale"] == "Search followed companies for applied AI roles."
        assert payload["selectionAssistantMessage"] == "The model selected strong roles, but persistence found duplicates."
        assert payload["selectionSkippedCandidateNotes"] == [{"candidateId": "J002", "reason": "Too generic."}]
        assert payload["replanReason"] == "zero_total_matches"
        assert payload["replanQueries"] == ["Applied AI Engineer"]
        assert payload["diagnostics"]["modelExplanation"]["plannerRationale"] == "Search followed companies for applied AI roles."
        assert payload["diagnostics"]["modelExplanation"]["selectionAssistantMessage"] == "The model selected strong roles, but persistence found duplicates."
        assert payload["diagnostics"]["modelReview"]["modelSelectedCount"] == 3
        assert payload["diagnostics"]["replanning"]["replanReasons"] == ["zero_total_matches"]

        try:
            job_discovery_service_module.get_job_search_run_status(
                run.id,
                session=session,
                auth=SimpleNamespace(candidate_profile=other),
            )
        except HTTPException as error:
            assert error.status_code == 404
        else:
            raise AssertionError("Expected run status read to be scoped to the owning candidate.")


def test_job_search_run_status_exposes_provider_scoped_diagnostics_without_sensitive_payloads() -> None:
    engine = create_seeded_engine()

    with Session(engine) as session:
        owner = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "rebekah-love"))
        assert owner is not None
        run = JobSearchRun(
            candidate_profile_id=owner.id,
            command_text="find jobs",
            search_plan_json={
                "searchMode": "followed_companies",
                "roleQueries": ["Applied AI Engineer"],
                "companyNames": ["Anthropic"],
                "locations": ["Remote US"],
                "remoteWorkModes": ["remote"],
                "salaryMin": 150000,
                "excludeTerms": ["management"],
                "providerStrategy": {"maxProviderPages": 2},
            },
            run_diagnostics_json={
                "userVisibleSummary": (
                    "I found roles from followed-company boards, but none matched strongly enough to save."
                ),
                "planner": {
                    "rationale": "Search followed company boards and broad providers for applied AI roles.",
                    "fallbackUsed": False,
                    "recentSearchesUsedCount": 0,
                },
                "selection": {
                    "assistantMessage": (
                        "I found roles from followed-company boards, but none matched strongly enough to save."
                    ),
                    "skippedCandidateNotes": [{"candidateId": "CAND-1", "reason": "Management-heavy role."}],
                    "clarifyingQuestions": [],
                },
                "replanning": {
                    "replansAttempted": 1,
                    "replanLimit": 1,
                    "replanningStatus": "attempted",
                    "replanningDecision": "triggered:zero_total_matches",
                    "replanReason": "zero_total_matches",
                    "replanReasons": ["zero_total_matches"],
                    "replanQueries": ["Applied AI Engineer"],
                },
                "providerDiagnostics": [
                    {
                        "providerName": "adzuna",
                        "providerType": "broad_search",
                        "configured": True,
                        "attempted": True,
                        "query": "Applied AI Engineer",
                        "requestCriteria": {
                            "what": "Applied AI Engineer",
                            "where": "Remote US",
                            "app_id": "hidden-app-id",
                            "app_key": "hidden-app-key",
                            "session_cookie": "hidden-cookie",
                            "authorization": "Bearer hidden-token",
                        },
                        "rawResultCount": 0,
                        "resultCount": 0,
                        "normalizedResultCount": 0,
                        "totalMatches": 0,
                        "page": 1,
                    },
                    {
                        "providerName": "Greenhouse",
                        "providerType": "ats_board",
                        "companyName": "Anthropic",
                        "boardToken": "anthropic",
                        "configured": True,
                        "attempted": True,
                        "rawResultCount": 28,
                        "resultCount": 28,
                        "normalizedResultCount": 28,
                    },
                ],
            },
            provider_names=["adzuna", "greenhouse"],
            status="completed",
            total_provider_results=28,
            candidate_pool_count=12,
            candidate_count_after_dedupe=12,
            model_selected_count=0,
            saved_count=0,
            updated_existing_count=0,
            duplicate_count=16,
            skipped_count=21,
            provider_error_count=0,
        )
        session.add(run)
        session.commit()
        session.refresh(run)

        payload = job_discovery_service_module.get_job_search_run_status(
            run.id,
            session=session,
            auth=SimpleNamespace(candidate_profile=owner),
        )

        diagnostics = payload["diagnostics"]
        assert diagnostics["searchCriteria"]["roleQueries"] == ["Applied AI Engineer"]
        assert diagnostics["searchCriteria"]["salaryMin"] == 150000
        assert diagnostics["modelReview"]["modelSelectedCount"] == 0
        assert diagnostics["modelExplanation"]["selectionAssistantMessage"] == (
            "I found roles from followed-company boards, but none matched strongly enough to save."
        )
        assert diagnostics["replanning"]["displayLabel"] == "Broad search reported 0 total matches"
        assert diagnostics["replanning"]["displayMessage"] == (
            "Broad search reported 0 total matches, while company board searches returned candidates."
        )
        assert diagnostics["replanning"]["triggerProviderName"] == "adzuna"
        assert diagnostics["replanning"]["triggerProviderType"] == "broad_search"
        assert diagnostics["replanning"]["companyBoardsReturnedCandidates"] is True
        assert diagnostics["replanning"]["providerResultsExisted"] is True
        assert diagnostics["replanning"]["candidatePoolExisted"] is True
        adzuna_diagnostics = diagnostics["providerDiagnostics"][0]
        assert adzuna_diagnostics["requestCriteria"] == {
            "what": "Applied AI Engineer",
            "where": "Remote US",
        }
        serialized = json.dumps(payload, sort_keys=True)
        assert "hidden-app-id" not in serialized
        assert "hidden-app-key" not in serialized
        assert "hidden-cookie" not in serialized
        assert "hidden-token" not in serialized


def test_latest_job_search_run_status_returns_newest_authenticated_run() -> None:
    engine = create_seeded_engine(include_second_profile=True)

    with Session(engine) as session:
        owner = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "rebekah-love"))
        other = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "alex-love"))
        assert owner is not None
        assert other is not None
        older_run = JobSearchRun(
            candidate_profile_id=owner.id,
            command_text="find older jobs",
            search_plan_json={},
            run_diagnostics_json={"userVisibleSummary": "Older run."},
            provider_names=[],
            status="completed",
            total_provider_results=1,
            candidate_pool_count=1,
            candidate_count_after_dedupe=1,
            model_selected_count=1,
            saved_count=1,
            updated_existing_count=0,
            duplicate_count=0,
            skipped_count=0,
            provider_error_count=0,
        )
        latest_run = JobSearchRun(
            candidate_profile_id=owner.id,
            command_text="find latest jobs",
            search_plan_json={},
            run_diagnostics_json={"userVisibleSummary": "Latest run."},
            provider_names=[],
            status="completed",
            total_provider_results=2,
            candidate_pool_count=2,
            candidate_count_after_dedupe=2,
            model_selected_count=0,
            saved_count=0,
            updated_existing_count=0,
            duplicate_count=2,
            skipped_count=0,
            provider_error_count=0,
        )
        other_run = JobSearchRun(
            candidate_profile_id=other.id,
            command_text="find other jobs",
            search_plan_json={},
            run_diagnostics_json={"userVisibleSummary": "Other run."},
            provider_names=[],
            status="completed",
            total_provider_results=99,
            candidate_pool_count=99,
            candidate_count_after_dedupe=99,
            model_selected_count=99,
            saved_count=99,
            updated_existing_count=0,
            duplicate_count=0,
            skipped_count=0,
            provider_error_count=0,
        )
        session.add_all([older_run, latest_run, other_run])
        session.flush()
        latest_run.created_at = older_run.created_at + timedelta(seconds=1)
        session.commit()

        payload = job_discovery_service_module.get_latest_job_search_run_status(
            session=session,
            auth=SimpleNamespace(candidate_profile=owner),
        )

        assert payload["id"] == latest_run.id
        assert payload["userVisibleSummary"] == "Latest run."
        assert payload["providerResultCount"] == 2


def test_start_job_discovery_run_reuses_recent_active_run() -> None:
    engine = create_seeded_engine()

    with Session(engine) as session:
        profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "rebekah-love"))
        assert profile is not None
        active_run = JobSearchRun(
            candidate_profile_id=profile.id,
            command_text="find jobs",
            search_plan_json={},
            provider_names=[],
            status="running",
            total_provider_results=0,
            candidate_pool_count=0,
            candidate_count_after_dedupe=0,
            model_selected_count=0,
            saved_count=0,
            updated_existing_count=0,
            duplicate_count=0,
            skipped_count=0,
            provider_error_count=0,
        )
        session.add(active_run)
        session.commit()
        session.refresh(active_run)

        run, created = job_discovery_service_module.start_job_discovery_run(
            JobDiscoveryRequest(
                latest_user_message="find more jobs",
                candidate_profile_slug=profile.slug,
            ),
            db_session=session,
            candidate_profile=profile,
            background_tasks=None,
        )

        runs = list(session.scalars(select(JobSearchRun)))
        assert created is False
        assert run.id == active_run.id
        assert len(runs) == 1


def test_job_discovery_background_success_marks_run_completed(tmp_path: Path, monkeypatch) -> None:
    engine = create_seeded_engine()
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(job_discovery_service_module, "load_settings", lambda: make_settings(tmp_path))

    def fake_run_job_discovery(request, *, db_session, settings, candidate_profile=None, job_search_run_id=None):
        assert job_search_run_id is not None
        return JobDiscoveryServiceResult(body={"ok": True, "result": {"jobSearchRunId": job_search_run_id}}, status_code=200)

    monkeypatch.setattr(job_discovery_service_module, "run_job_discovery", fake_run_job_discovery)

    with Session(engine) as session:
        profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "rebekah-love"))
        assert profile is not None
        run, created = job_discovery_service_module.start_job_discovery_run(
            JobDiscoveryRequest(latest_user_message="find jobs", candidate_profile_slug=profile.slug),
            db_session=session,
            candidate_profile=profile,
            background_tasks=None,
        )
        assert created is True
        run_id = run.id
        profile_id = profile.id

    job_discovery_service_module.run_job_discovery_background(
        run_id,
        profile_id,
        {
            "latest_user_message": "find jobs",
            "candidate_profile_slug": "rebekah-love",
            "active_workspace": "jobs",
            "client_context": {},
            "router_extracted": None,
        },
        session_factory=factory,
    )

    with Session(engine) as session:
        run = session.get(JobSearchRun, run_id)
        assert run is not None
        assert run.status == "completed"
        assert run.started_at is not None
        assert run.completed_at is not None


def test_job_discovery_background_failure_marks_run_failed(tmp_path: Path, monkeypatch) -> None:
    engine = create_seeded_engine()
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(job_discovery_service_module, "load_settings", lambda: make_settings(tmp_path))

    def fake_run_job_discovery(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(job_discovery_service_module, "run_job_discovery", fake_run_job_discovery)

    with Session(engine) as session:
        profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "rebekah-love"))
        assert profile is not None
        run, _ = job_discovery_service_module.start_job_discovery_run(
            JobDiscoveryRequest(latest_user_message="find jobs", candidate_profile_slug=profile.slug),
            db_session=session,
            candidate_profile=profile,
            background_tasks=None,
        )
        run_id = run.id
        profile_id = profile.id

    job_discovery_service_module.run_job_discovery_background(
        run_id,
        profile_id,
        {
            "latest_user_message": "find jobs",
            "candidate_profile_slug": "rebekah-love",
            "active_workspace": "jobs",
            "client_context": {},
            "router_extracted": None,
        },
        session_factory=factory,
    )

    with Session(engine) as session:
        run = session.get(JobSearchRun, run_id)
        assert run is not None
        assert run.status == "failed"
        assert "provider unavailable" in (run.error or "")


def test_job_discovery_prompts_for_targets_on_generic_request(tmp_path: Path) -> None:
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
        assert result.body["result"]["jobs"] == []
        assert result.body["result"]["profileTargetsRequired"] is True
        assert result.body["result"]["jobDiscoveryMode"] == "target_required"
        assert "complete your target details" in result.body["result"]["assistantMessage"]
        assert len(session.scalars(select(CandidateSavedJob)).all()) == 0


@SKIP_LEGACY_LIVE_PROVIDER_DISCOVERY
def test_job_discovery_allows_explicit_broad_request_without_saved_targets(tmp_path: Path) -> None:
    engine = create_seeded_engine()

    with Session(engine) as session:
        result = run_job_discovery(
            JobDiscoveryRequest(
                latest_user_message="Run a broad exploratory job search.",
                candidate_profile_slug="rebekah-love",
            ),
            db_session=session,
            settings=make_settings(tmp_path),
        )

        assert result.status_code == 200
        assert result.body["ok"] is True
        assert result.body["result"]["savedCount"] == 2


@SKIP_LEGACY_LIVE_PROVIDER_DISCOVERY
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
        assert second.body["result"]["assistantMessage"] == job_discovery_service_module.NO_MODEL_SELECTION_EXPLANATION_FALLBACK
        assert second.body["result"]["userVisibleSummary"] == job_discovery_service_module.NO_MODEL_SELECTION_EXPLANATION_FALLBACK
        assert len(session.scalars(select(JobPosting)).all()) == 2
        assert len(session.scalars(select(CandidateSavedJob)).all()) == 2
        for link in session.scalars(select(CandidateSavedJob)).all():
            assert link.added_at == first_added_at[link.job.normalized_url]


@SKIP_LEGACY_LIVE_PROVIDER_DISCOVERY
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


def test_provider_queries_use_command_role_before_saved_targets() -> None:
    queries = infer_job_search_role_queries(
        "Find museum registrar jobs to apply to.",
        target_context={"target_role_titles": ["AI Product Engineer", "Developer Tools Engineer"]},
        private_profile_context={
            "profile_basics": {
                "headline": "Applied AI Systems Engineer | RAG, LLM Evaluation & Production AI Platforms",
            },
            "summary": "Strong fit for applied AI and data-intensive product roles.",
        },
    )

    assert queries[:3] == ["Museum Registrar", "AI Product Engineer", "Developer Tools Engineer"]
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


def test_provider_queries_for_broad_exploratory_request_do_not_use_meta_command() -> None:
    request = JobDiscoveryRequest(latest_user_message="let's do a broad exploratory job search", candidate_profile_slug="rebekah-love")
    queries = build_provider_job_search_queries(
        request,
        current_saved_companies=[],
        target_context={},
        private_profile_context={
            "profile_basics": {
                "headline": "Candidate profile setup in progress",
                "summary": "Profile setup in progress.",
            },
            "targets": {},
        },
    )

    assert queries == ["jobs"]
    assert "Lets Do A Broad Exploratory Job Search" not in queries


def test_provider_queries_for_broad_request_use_profile_skills_before_generic_jobs() -> None:
    request = JobDiscoveryRequest(latest_user_message="let's do a broad exploratory job search", candidate_profile_slug="rebekah-love")
    queries = build_provider_job_search_queries(
        request,
        current_saved_companies=[],
        target_context={},
        private_profile_context={
            "profile_basics": {
                "headline": "Candidate profile setup in progress",
                "summary": "Profile setup in progress.",
            },
            "targets": {},
            "draft_items": [
                {"type": "skill", "skill": "Ceramic sculpture"},
                {"type": "skill", "skill": "Metal fabrication"},
            ],
        },
    )

    assert queries[:2] == ["Ceramic sculpture", "Metal fabrication"]
    assert "jobs" not in queries


def test_provider_queries_keep_location_out_of_keyword_query() -> None:
    queries = build_provider_job_search_queries_from_plan(
        JobDiscoveryRequest(latest_user_message="Find AI jobs in Connecticut", candidate_profile_slug="rebekah-love"),
        search_plan=JobSearchPlan(searchMode="broad", roleQueries=["AI Engineer"], locations=["Connecticut"]),
        current_saved_companies=[],
        target_context={},
        private_profile_context={},
    )

    assert queries == ["AI Engineer"]


def test_provider_query_precedence_uses_command_before_profile_fallbacks() -> None:
    queries = infer_job_search_role_queries(
        "find conservation technician jobs",
        target_context={
            "target_role_titles": ["Gallery Operations Manager"],
            "target_role_families": ["Arts Administration"],
            "domains_or_industries": "Museums",
        },
        private_profile_context={
            "profile_basics": {"headline": "Ceramic Artist | Installation and fabrication"},
            "draft_items": [
                {"type": "experience", "title": "Studio Assistant"},
                {"type": "skill", "skill": "Ceramic sculpture"},
            ],
        },
    )

    assert queries[:6] == [
        "Conservation Technician",
        "Gallery Operations Manager",
        "Arts Administration",
        "Ceramic Artist",
        "Museums",
        "Studio Assistant",
    ]


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
    assert result.salary_min == 150000
    assert result.salary_max == 180000
    assert result.salary_currency == "USD"
    assert result.salary_text == "USD 150,000-180,000"
    assert result.posting_date is not None
    assert result.source_updated_at is not None


def test_adzuna_uses_search_plan_location_as_where_not_keyword(tmp_path: Path) -> None:
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
        latest_user_message="Find AI jobs in Connecticut",
        search_queries=["AI Engineer"],
        results_per_provider=12,
        current_saved_companies=[],
        target_context={},
        private_profile_context={},
        user_constraints=[],
        search_plan=JobSearchPlan(searchMode="broad", roleQueries=["AI Engineer"], locations=["Connecticut"]),
        locations=["Connecticut"],
    )

    url, params = build_adzuna_request(settings, request, query=request.search_queries[0])

    assert url == "https://api.adzuna.com/v1/api/jobs/us/search/1"
    assert params["what"] == "AI Engineer"
    assert params["where"] == "Connecticut"


def test_adzuna_salary_values_are_rounded_and_currency_coded(tmp_path: Path) -> None:
    settings = make_settings(
        tmp_path,
        model_provider="mock",
        job_discovery_source="none",
        job_discovery_providers=("adzuna",),
        adzuna_app_id="app-id",
        adzuna_app_key="app-key",
        adzuna_country="us",
    )
    result = normalize_adzuna_result(
        {
            "id": "adz-1",
            "title": "Studio Manager",
            "company": {"display_name": "Provider Co"},
            "redirect_url": "https://www.adzuna.com/land/ad/1",
            "description": "Run the studio.",
            "salary_min": 38469.71,
            "salary_max": 50210.44,
        },
        query="Studio Manager",
        settings=settings,
    )

    assert result is not None
    assert result.salary_min == 38470
    assert result.salary_max == 50210
    assert result.salary_currency == "USD"
    assert result.salary_text == "USD 38,470-50,210"


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


def test_greenhouse_url_parser_supports_public_and_api_urls() -> None:
    cases = [
        ("https://job-boards.greenhouse.io/examplecivic", "examplecivic", None),
        ("https://job-boards.greenhouse.io/examplecivic/jobs/123", "examplecivic", "123"),
        ("https://boards.greenhouse.io/examplecivic", "examplecivic", None),
        ("https://boards.greenhouse.io/examplecivic/jobs/123", "examplecivic", "123"),
        ("https://boards-api.greenhouse.io/v1/boards/examplecivic/jobs", "examplecivic", None),
        ("https://boards-api.greenhouse.io/v1/boards/examplecivic/jobs/123", "examplecivic", "123"),
    ]

    for url, token, job_id in cases:
        parsed = parse_greenhouse_url(url)
        assert parsed is not None
        assert parsed.provider == "greenhouse"
        assert parsed.board_token == token
        assert parsed.job_id == job_id
        assert parsed.jobs_api_url == canonical_greenhouse_jobs_api_url(token)


@SKIP_LEGACY_LIVE_PROVIDER_DISCOVERY
def test_greenhouse_url_ingestion_upserts_company_job_and_candidate_links(monkeypatch, tmp_path: Path) -> None:
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
                            "id": 4680768006,
                            "title": "Applied AI Engineer",
                            "absolute_url": "https://job-boards.greenhouse.io/hightouch/jobs/4680768006",
                            "location": {"name": "Remote"},
                            "content": "<p>Build reliable data activation systems.</p>",
                        }
                    ]
                }
            ).encode("utf-8")

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: FakeResponse())
    engine = create_seeded_engine()
    settings = make_settings(tmp_path, job_discovery_source="none", job_discovery_providers=())

    with Session(engine) as session:
        profile = session.scalar(select(job_discovery_service_module.CandidateProfile).where(job_discovery_service_module.CandidateProfile.slug == "rebekah-love"))
        assert profile is not None
        upsert_greenhouse_companies_for_candidate(session, candidate_profile_id=profile.id)
        session.commit()

        result = run_job_discovery(
            JobDiscoveryRequest(
                latest_user_message="Add this job to my list https://job-boards.greenhouse.io/hightouch/jobs/4680768006",
                candidate_profile_slug="rebekah-love",
            ),
            db_session=session,
            settings=settings,
        )

        assert result.status_code == 200
        assert result.body["result"]["savedCount"] == 1
        job = session.scalar(select(JobPosting).where(JobPosting.source_result_id == "hightouch:4680768006"))
        assert job is not None
        assert job.company_id is not None
        assert job.company_name == "Hightouch"
        assert job.ats_provider == "greenhouse"
        assert job.ats_board_token == "hightouch"
        company = session.get(Company, job.company_id)
        assert company is not None
        assert company.name == "Hightouch"
        assert company.greenhouse_board_token == "hightouch"
        assert company.job_listings_url == "https://boards-api.greenhouse.io/v1/boards/hightouch/jobs"
        saved_link = session.scalar(select(CandidateSavedJob).where(CandidateSavedJob.job_id == job.id))
        assert saved_link is not None
        assert saved_link.status == "new"

        duplicate = run_job_discovery(
            JobDiscoveryRequest(
                latest_user_message="Save this job https://job-boards.greenhouse.io/hightouch/jobs/4680768006",
                candidate_profile_slug="rebekah-love",
            ),
            db_session=session,
            settings=settings,
        )

        assert duplicate.status_code == 200
        assert duplicate.body["result"]["savedCount"] == 0
        assert duplicate.body["result"]["updatedExistingCount"] == 1
        assert len(session.scalars(select(JobPosting)).all()) == 1
        assert len(session.scalars(select(CandidateSavedJob)).all()) == 1


@SKIP_LEGACY_LIVE_PROVIDER_DISCOVERY
def test_greenhouse_url_ingestion_repairs_token_derived_company_name(monkeypatch, tmp_path: Path) -> None:
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
                            "id": 4680768006,
                            "title": "Applied AI Engineer",
                            "absolute_url": "https://job-boards.greenhouse.io/solutions/jobs/4680768006",
                            "location": {"name": "Remote"},
                            "content": "<p>Build reliable systems.</p>",
                        }
                    ]
                }
            ).encode("utf-8")

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: FakeResponse())
    engine = create_seeded_engine()
    settings = make_settings(tmp_path, job_discovery_source="none", job_discovery_providers=())

    with Session(engine) as session:
        profile = session.scalar(select(job_discovery_service_module.CandidateProfile).where(job_discovery_service_module.CandidateProfile.slug == "rebekah-love"))
        assert profile is not None
        company = Company(
            name="Solutions",
            normalized_name="solutions",
            greenhouse_board_token="solutions",
            job_listings_url="https://boards-api.greenhouse.io/v1/boards/solutions/jobs",
            source_urls=["https://boards-api.greenhouse.io/v1/boards/solutions/jobs"],
        )
        session.add(company)
        session.flush()
        session.add(CandidateCompany(candidate_profile_id=profile.id, company_id=company.id, review_status="new"))
        session.commit()

        result = run_job_discovery(
            JobDiscoveryRequest(
                latest_user_message="Add this job to my list https://job-boards.greenhouse.io/solutions/jobs/4680768006",
                candidate_profile_slug="rebekah-love",
            ),
            db_session=session,
            settings=settings,
        )

        assert result.status_code == 200
        job = session.scalar(select(JobPosting).where(JobPosting.source_result_id == "solutions:4680768006"))
        assert job is not None
        assert job.company_name == "Cadence Solutions"
        repaired = session.get(Company, company.id)
        assert repaired is not None
        assert repaired.name == "Cadence Solutions"
        assert repaired.normalized_name == "cadence solutions"


def test_greenhouse_seed_is_idempotent_and_does_not_overwrite_non_empty_company_fields() -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = session.scalar(select(job_discovery_service_module.CandidateProfile).where(job_discovery_service_module.CandidateProfile.slug == "rebekah-love"))
        assert profile is not None
        company = Company(
            name="Hightouch",
            normalized_name="hightouch",
            website_url="https://www.hightouch.com",
            greenhouse_board_token="hightouch",
            job_listings_url="https://custom.example/jobs",
            source_urls=["https://custom.example/jobs"],
        )
        session.add(company)
        session.commit()

        first = upsert_greenhouse_companies_for_candidate(session, candidate_profile_id=profile.id)
        second = upsert_greenhouse_companies_for_candidate(session, candidate_profile_id=profile.id)
        session.commit()

        assert len(first) == 9
        assert len(second) == 9
        hightouch = session.scalar(select(Company).where(Company.greenhouse_board_token == "hightouch"))
        assert hightouch is not None
        assert hightouch.website_url == "https://www.hightouch.com"
        assert hightouch.job_listings_url == "https://custom.example/jobs"
        assert len(session.scalars(select(Company).where(Company.greenhouse_board_token == "hightouch")).all()) == 1
        assert len(session.scalars(select(CandidateCompany).where(CandidateCompany.candidate_profile_id == profile.id)).all()) == 9


def test_provider_routing_prefers_saved_greenhouse_company_board() -> None:
    providers = resolve_job_discovery_providers(("adzuna", "greenhouse", "mock"))
    request = JobSearchRequest(
        latest_user_message="Find jobs at Hightouch",
        search_queries=["AI Engineer"],
        results_per_provider=20,
        current_saved_companies=[
            {
                "name": "Hightouch",
                "greenhouse_board_token": "hightouch",
                "job_listings_url": "https://boards-api.greenhouse.io/v1/boards/hightouch/jobs",
            }
        ],
        target_context={},
        private_profile_context={},
        user_constraints=[],
        search_plan=JobSearchPlan(searchMode="company_specific", roleQueries=["AI Engineer"], companyNames=["Hightouch"]),
        company_names=["Hightouch"],
    )

    routed, diagnostics = route_job_discovery_providers(providers, request)

    assert [provider.provider_name for provider in routed] == ["greenhouse"]
    assert diagnostics[0].reason == "saved_company_board_token"


def test_provider_routing_adds_greenhouse_for_saved_company_when_settings_only_have_broad_provider() -> None:
    providers = resolve_job_discovery_providers(("adzuna",))
    request = JobSearchRequest(
        latest_user_message="Find jobs at Solutions",
        search_queries=["Applied AI Engineer"],
        results_per_provider=20,
        current_saved_companies=[
            {
                "name": "Cadence Solutions",
                "greenhouse_board_token": "solutions",
                "job_listings_url": "https://boards-api.greenhouse.io/v1/boards/solutions/jobs",
            }
        ],
        target_context={},
        private_profile_context={},
        user_constraints=[],
        search_plan=JobSearchPlan(searchMode="company_specific", roleQueries=["Applied AI Engineer"], companyNames=["Solutions"]),
        company_names=["Solutions"],
    )

    routed, diagnostics = route_job_discovery_providers(providers, request)

    assert [provider.provider_name for provider in routed] == ["greenhouse"]
    assert diagnostics[0].reason == "saved_company_board_token_dynamic_provider"


def test_greenhouse_followed_company_search_filters_each_board_by_role_query(monkeypatch, tmp_path: Path) -> None:
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
        token = "hightouch" if "hightouch" in url else "anthropic"
        return FakeResponse(
            {
                "jobs": [
                    {
                        "id": f"{token}-1",
                        "title": "Applied AI Engineer",
                        "absolute_url": f"https://job-boards.greenhouse.io/{token}/jobs/1",
                        "location": {"name": "Remote"},
                        "content": "<p>Applied AI platform role.</p>",
                    }
                ]
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    request = JobSearchRequest(
        latest_user_message="Find jobs from my companies list",
        search_queries=["Anthropic Applied AI Engineer remote", "Hightouch Applied AI Engineer remote"],
        results_per_provider=20,
        current_saved_companies=[
            {"name": "Anthropic", "greenhouse_board_token": "anthropic"},
            {"name": "Hightouch", "greenhouse_board_token": "hightouch"},
        ],
        target_context={},
        private_profile_context={},
        user_constraints=[],
        search_plan=JobSearchPlan(
            searchMode="followed_companies",
            roleQueries=["Applied AI Engineer"],
            companyNames=["Anthropic", "Hightouch"],
        ),
        company_names=["Anthropic", "Hightouch"],
    )

    outcome = GreenhouseJobDiscoveryProvider().search(
        request,
        make_settings(tmp_path, greenhouse_board_tokens=()),
    )

    assert [result.company_name for result in outcome.results] == ["Anthropic", "Hightouch"]
    assert {diagnostic.query for diagnostic in outcome.diagnostics} == {"Applied AI Engineer"}


def test_greenhouse_without_board_targets_is_skipped_without_failing_broad_search(tmp_path: Path) -> None:
    request = JobSearchRequest(
        latest_user_message="Find me some jobs to apply to",
        search_queries=["Applied AI Systems Engineer remote"],
        results_per_provider=20,
        current_saved_companies=[],
        target_context={},
        private_profile_context={},
        user_constraints=[],
        search_plan=JobSearchPlan(searchMode="broad", roleQueries=["Applied AI Systems Engineer"]),
        company_names=[],
    )

    outcome = run_configured_job_providers(
        [GreenhouseJobDiscoveryProvider()],
        request,
        make_settings(tmp_path, job_discovery_providers=("greenhouse",), greenhouse_board_tokens=()),
    )

    assert outcome.results == []
    assert outcome.errors == []
    assert len(outcome.diagnostics) == 1
    assert outcome.diagnostics[0].provider_name == "greenhouse"
    assert outcome.diagnostics[0].configured is False
    assert outcome.diagnostics[0].attempted is False
    assert outcome.diagnostics[0].error is None
    assert outcome.diagnostics[0].reason == "no_board_targets_available"


def test_partial_broad_provider_errors_do_not_fail_after_company_board_results() -> None:
    outcome = ProviderSearchOutcome(
        results=[
            LiveJobSourceResult(
                title="Applied AI Engineer",
                company_name="Anthropic",
                job_url="https://job-boards.greenhouse.io/anthropic/jobs/1",
                source_provider="greenhouse",
                provider_type="ats_board",
            )
        ],
        diagnostics=[
            ProviderDiagnostic(
                provider_name="greenhouse",
                provider_type="ats_board",
                configured=True,
                attempted=True,
                result_count=1,
            ),
            ProviderDiagnostic(
                provider_name="adzuna",
                provider_type="broad_search",
                configured=True,
                attempted=True,
                result_count=0,
                error="Adzuna request failed with HTTP 503.",
            ),
        ],
        errors=["Adzuna request failed with HTTP 503."],
    )

    assert should_tolerate_partial_company_board_errors(
        outcome,
        JobSearchPlan(searchMode="followed_companies", roleQueries=["Applied AI Engineer"], companyNames=["Anthropic"]),
    )


@SKIP_LEGACY_LIVE_PROVIDER_DISCOVERY
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



@SKIP_LEGACY_LIVE_PROVIDER_DISCOVERY
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
            if request.task == "job_search_planning":
                return fake_job_search_planner_response()
            assert request.task == "job_candidate_selection"
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


@SKIP_LEGACY_LIVE_PROVIDER_DISCOVERY
def test_zero_model_selection_persists_model_authored_explanation(monkeypatch, tmp_path: Path) -> None:
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
                            "title": ".NET Engineering Manager",
                            "company": {"display_name": "Followed Co"},
                            "redirect_url": "https://jobs.example.test/dotnet-manager",
                            "description": "Manage a .NET application team.",
                        },
                        {
                            "id": "adz-2",
                            "title": "Junior Software Engineer",
                            "company": {"display_name": "Followed Co"},
                            "redirect_url": "https://jobs.example.test/junior-software",
                            "description": "Entry-level backend role below target compensation.",
                        },
                    ]
                }
            ).encode("utf-8")

    class ZeroSelectionConnector:
        def generate(self, request):
            if request.task == "job_search_planning":
                return fake_job_search_planner_response(role_query="Applied AI Engineer")
            assert request.task == "job_candidate_selection"
            payload = json.loads(request.messages[-1].content)
            return ModelResponse(
                text=json.dumps(
                    {
                        "assistantMessage": (
                            "I found jobs at followed companies, but none matched your target profile closely: "
                            "most were .NET management roles or below your target compensation."
                        ),
                        "selectedJobs": [],
                        "skippedCandidateNotes": [
                            {"candidateId": payload["candidate_jobs"][0]["candidateId"], "reason": "Management-focused .NET role."},
                            {"candidateId": payload["candidate_jobs"][1]["candidateId"], "reason": "Junior role below target compensation."},
                        ],
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
        profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "rebekah-love"))
        assert profile is not None
        result = run_job_discovery(
            JobDiscoveryRequest(latest_user_message="Find applied AI jobs at followed companies.", candidate_profile_slug="rebekah-love"),
            connector=ZeroSelectionConnector(),
            db_session=session,
            settings=settings,
        )

        assert result.status_code == 200
        assert result.body["result"]["modelSelectedCount"] == 0
        assert result.body["result"]["savedCount"] == 0
        assert "none matched your target profile closely" in result.body["result"]["assistantMessage"]
        assert result.body["result"]["userVisibleSummary"] == result.body["result"]["assistantMessage"]
        assert result.body["result"]["selectionAssistantMessage"] == result.body["result"]["assistantMessage"]
        assert result.body["result"]["plannerRationale"] == "Fake planner response for tests."

        run = session.scalar(select(JobSearchRun))
        assert run is not None
        payload = job_discovery_service_module.get_job_search_run_status(
            run.id,
            session=session,
            auth=SimpleNamespace(candidate_profile=profile),
        )
        assert payload["modelSelectedCount"] == 0
        assert payload["savedCount"] == 0
        assert payload["userVisibleSummary"] == result.body["result"]["assistantMessage"]
        assert payload["userSummary"] == result.body["result"]["assistantMessage"]
        assert payload["selectionAssistantMessage"] == result.body["result"]["assistantMessage"]
        assert payload["plannerRationale"] == "Fake planner response for tests."
        assert payload["selectionSkippedCandidateNotes"][0]["reason"] == "Management-focused .NET role."


@SKIP_LEGACY_LIVE_PROVIDER_DISCOVERY
def test_zero_model_selection_without_meaningful_explanation_uses_transparent_fallback(monkeypatch, tmp_path: Path) -> None:
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
                            "description": "Generic backend services.",
                        }
                    ]
                }
            ).encode("utf-8")

    class GenericMessageConnector:
        def generate(self, request):
            if request.task == "job_search_planning":
                return fake_job_search_planner_response(role_query="Applied AI Engineer")
            assert request.task == "job_candidate_selection"
            payload = json.loads(request.messages[-1].content)
            return ModelResponse(
                text=json.dumps(
                    {
                        "assistantMessage": "I reviewed the live provider candidates and selected the strongest matches.",
                        "selectedJobs": [],
                        "skippedCandidateNotes": [
                            {"candidateId": payload["candidate_jobs"][0]["candidateId"], "reason": "Generic role fit."}
                        ],
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
        profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "rebekah-love"))
        assert profile is not None
        result = run_job_discovery(
            JobDiscoveryRequest(latest_user_message="Find applied AI jobs.", candidate_profile_slug="rebekah-love"),
            connector=GenericMessageConnector(),
            db_session=session,
            settings=settings,
        )

        assert result.status_code == 200
        assert result.body["result"]["modelSelectedCount"] == 0
        assert result.body["result"]["savedCount"] == 0
        assert result.body["result"]["assistantMessage"] == job_discovery_service_module.NO_MODEL_SELECTION_EXPLANATION_FALLBACK
        assert result.body["result"]["selectionAssistantMessage"] is None

        run = session.scalar(select(JobSearchRun))
        assert run is not None
        payload = job_discovery_service_module.get_job_search_run_status(
            run.id,
            session=session,
            auth=SimpleNamespace(candidate_profile=profile),
        )
        assert payload["userVisibleSummary"] == job_discovery_service_module.NO_MODEL_SELECTION_EXPLANATION_FALLBACK
        assert payload["message"] == job_discovery_service_module.NO_MODEL_SELECTION_EXPLANATION_FALLBACK


@SKIP_LEGACY_LIVE_PROVIDER_DISCOVERY
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


@SKIP_LEGACY_LIVE_PROVIDER_DISCOVERY
def test_model_selection_truncation_retries_with_compact_payload(monkeypatch, tmp_path: Path) -> None:
    selection_calls = []

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
            if request.task == "job_search_planning":
                return fake_job_search_planner_response()
            assert request.task == "job_candidate_selection"
            selection_calls.append(request)
            if len(selection_calls) == 1:
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
        assert len(selection_calls) == 2
        assert result.body["result"]["savedCount"] == 1
        assert result.body["result"]["selectedCandidateIds"] == ["J001"]


@SKIP_LEGACY_LIVE_PROVIDER_DISCOVERY
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


@SKIP_LEGACY_LIVE_PROVIDER_DISCOVERY
def test_provider_zero_results_are_logged(monkeypatch, tmp_path: Path) -> None:
    class FakeResponse:
        status = 200
        headers = {"content-type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, *_args):
            return json.dumps({"results": []}).encode("utf-8")

    log_messages = []

    def capture_log(_level, message, *args, **_kwargs):
        log_messages.append(message % args if args else message)

    monkeypatch.setattr(job_discovery_service_module.logger, "log", capture_log)
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
        assert result.body["result"]["replansAttempted"] == settings.job_discovery_search_replan_limit
        assert result.body["result"]["replanLimit"] == settings.job_discovery_search_replan_limit
        assert result.body["result"]["replanningStatus"] == "attempted"
        assert result.body["result"]["replanReasons"] == ["no_provider_results"]
        assert any("Job discovery replanning triggered" in message for message in log_messages)
        assert any('"replansAttempted": 1' in message for message in log_messages)


@SKIP_LEGACY_LIVE_PROVIDER_DISCOVERY
def test_zero_result_provider_search_replans_with_context(monkeypatch, tmp_path: Path) -> None:
    planner_payloads = []
    selection_payloads = []
    provider_calls = 0

    class FakeResponse:
        status = 200
        headers = {"content-type": "application/json"}

        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, *_args):
            return json.dumps(self.payload).encode("utf-8")

    class ReplanningConnector:
        def generate(self, request):
            if request.task == "job_search_planning":
                payload = json.loads(request.messages[-1].content)
                planner_payloads.append(payload)
                if len(planner_payloads) == 1:
                    return fake_job_search_planner_response(role_query="No Match AI Engineer", requested_result_goal=10)
                return fake_job_search_planner_response(role_query="AI Platform Engineer", requested_result_goal=10)
            assert request.task == "job_candidate_selection"
            payload = json.loads(request.messages[-1].content)
            selection_payloads.append(payload)
            selected_candidate = payload["candidate_jobs"][0]
            return ModelResponse(
                text=json.dumps(
                    {
                        "assistantMessage": "Selected the replanned provider result.",
                        "selectedJobs": [
                            {
                                "candidateId": selected_candidate["candidateId"],
                                "fitSummary": "Strong AI platform fit.",
                                "rank": 1,
                                "selectionReason": "Found after replanning from the zero-result query.",
                                "concerns": [],
                            }
                        ],
                        "skippedCandidateNotes": [],
                        "clarifyingQuestions": [],
                    }
                ),
                provider="fake",
                model="fake-model",
            )

    def fake_urlopen(_request, timeout):
        nonlocal provider_calls
        provider_calls += 1
        if provider_calls == 1:
            return FakeResponse({"count": 0, "results": []})
        return FakeResponse(
            {
                "count": 1,
                "results": [
                    {
                        "id": "adz-replanned-1",
                        "title": "AI Platform Engineer",
                        "company": {"display_name": "Replanned AI"},
                        "redirect_url": "https://jobs.example.test/replanned-ai-platform",
                        "description": "Build AI workflow automation.",
                    }
                ],
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    engine = create_seeded_engine()
    settings = replace(
        make_settings(
            tmp_path,
            model_provider="gemini",
            job_discovery_source="none",
            job_discovery_providers=("adzuna",),
            adzuna_app_id="app-id",
            adzuna_app_key="app-key",
        ),
        job_discovery_results_per_provider=10,
        job_discovery_save_limit=5,
        job_discovery_search_replan_limit=1,
    )

    with Session(engine) as session:
        result = run_job_discovery(
            JobDiscoveryRequest(latest_user_message="Find AI platform jobs.", candidate_profile_slug="rebekah-love"),
            connector=ReplanningConnector(),
            db_session=session,
            settings=settings,
        )

        assert result.status_code == 200
        assert len(planner_payloads) == 2
        assert provider_calls >= 2
        assert planner_payloads[1]["replan_context"]["reason"] == "zero_total_matches"
        assert planner_payloads[1]["replan_context"]["priorSearchPlan"]["roleQueries"] == ["No Match AI Engineer"]
        assert planner_payloads[1]["replan_context"]["providerResultCount"] == 0
        assert result.body["result"]["replansAttempted"] == 1
        assert result.body["result"]["replanReasons"] == ["zero_total_matches"]
        assert result.body["result"]["savedCount"] == 1
        assert selection_payloads[0]["candidate_jobs"][0]["title"] == "AI Platform Engineer"
        run = session.scalar(select(JobSearchRun))
        assert run is not None
        assert run.replans_attempted == 1
        assert run.search_plan_json["roleQueries"] == ["AI Platform Engineer"]
        assert len(session.scalars(select(JobSearchQueryRun)).all()) == 2


@SKIP_LEGACY_LIVE_PROVIDER_DISCOVERY
def test_zero_result_replanning_does_not_exceed_configured_limit(monkeypatch, tmp_path: Path) -> None:
    planner_payloads = []
    provider_calls = 0

    class FakeResponse:
        status = 200
        headers = {"content-type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, *_args):
            return json.dumps({"count": 0, "results": []}).encode("utf-8")

    class ReplanningConnector:
        def generate(self, request):
            if request.task == "job_search_planning":
                payload = json.loads(request.messages[-1].content)
                planner_payloads.append(payload)
                return fake_job_search_planner_response(
                    role_query=f"No Match AI Engineer {len(planner_payloads)}",
                    requested_result_goal=10,
                )
            raise AssertionError("Candidate selection should not run without provider candidates.")

    def fake_urlopen(_request, timeout):
        nonlocal provider_calls
        provider_calls += 1
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    engine = create_seeded_engine()
    settings = replace(
        make_settings(
            tmp_path,
            model_provider="gemini",
            job_discovery_source="none",
            job_discovery_providers=("adzuna",),
            adzuna_app_id="app-id",
            adzuna_app_key="app-key",
        ),
        job_discovery_results_per_provider=10,
        job_discovery_save_limit=5,
        job_discovery_search_replan_limit=1,
    )

    with Session(engine) as session:
        result = run_job_discovery(
            JobDiscoveryRequest(latest_user_message="Find AI platform jobs.", candidate_profile_slug="rebekah-love"),
            connector=ReplanningConnector(),
            db_session=session,
            settings=settings,
        )

        assert result.status_code == 200
        assert len(planner_payloads) == 2
        assert provider_calls == 2
        assert result.body["result"]["replansAttempted"] == 1
        assert result.body["result"]["replanLimit"] == 1
        assert result.body["result"]["savedCount"] == 0


@SKIP_LEGACY_LIVE_PROVIDER_DISCOVERY
def test_low_candidate_pool_does_not_replan_when_total_matches_are_exhausted(monkeypatch, tmp_path: Path) -> None:
    planner_payloads = []

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
                    "count": 1,
                    "results": [
                        {
                            "id": "adz-1",
                            "title": "AI Platform Engineer",
                            "company": {"display_name": "One Match AI"},
                            "redirect_url": "https://jobs.example.test/one-match-ai-platform",
                            "description": "Build AI workflow automation.",
                        }
                    ],
                }
            ).encode("utf-8")

    class Connector:
        def generate(self, request):
            if request.task == "job_search_planning":
                planner_payloads.append(json.loads(request.messages[-1].content))
                return fake_job_search_planner_response(role_query="AI Platform Engineer", requested_result_goal=10)
            assert request.task == "job_candidate_selection"
            payload = json.loads(request.messages[-1].content)
            selected_candidate = payload["candidate_jobs"][0]
            return ModelResponse(
                text=json.dumps(
                    {
                        "assistantMessage": "Selected the only provider-backed match.",
                        "selectedJobs": [
                            {
                                "candidateId": selected_candidate["candidateId"],
                                "fitSummary": "Good platform fit.",
                                "rank": 1,
                                "selectionReason": "The provider reported this is the only match.",
                                "concerns": [],
                            }
                        ],
                        "skippedCandidateNotes": [],
                        "clarifyingQuestions": [],
                    }
                ),
                provider="fake",
                model="fake-model",
            )

    log_messages = []

    def capture_log(_level, message, *args, **_kwargs):
        log_messages.append(message % args if args else message)

    monkeypatch.setattr(job_discovery_service_module.logger, "log", capture_log)
    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: FakeResponse())
    engine = create_seeded_engine()
    settings = replace(
        make_settings(
            tmp_path,
            model_provider="gemini",
            job_discovery_source="none",
            job_discovery_providers=("adzuna",),
            adzuna_app_id="app-id",
            adzuna_app_key="app-key",
        ),
        job_discovery_results_per_provider=10,
        job_discovery_save_limit=5,
        job_discovery_search_replan_limit=1,
    )

    with Session(engine) as session:
        result = run_job_discovery(
            JobDiscoveryRequest(latest_user_message="Find AI platform jobs.", candidate_profile_slug="rebekah-love"),
            connector=Connector(),
            db_session=session,
            settings=settings,
        )

        assert result.status_code == 200
        assert len(planner_payloads) == 1
        assert result.body["result"]["replansAttempted"] == 0
        assert result.body["result"]["replanningStatus"] == "not_needed"
        assert result.body["result"]["replanningDecision"] == "provider_results_exhausted"
        assert result.body["result"]["savedCount"] == 1
        assert any("Job discovery replanning skipped" in message for message in log_messages)
        assert any("provider_results_exhausted" in message for message in log_messages)


@SKIP_LEGACY_LIVE_PROVIDER_DISCOVERY
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
        assert result.body["providerDiagnostics"][0]["requestCriteria"]["what"] == "Applied AI"
        assert result.body["providerDiagnostics"][0]["requestCriteria"]["where"] is None
        assert "app-id" not in json.dumps(result.body["providerDiagnostics"][0]["requestCriteria"])


def test_job_discovery_run_lifecycle_is_logged(monkeypatch, tmp_path: Path) -> None:
    messages: list[str] = []

    def capture_warning(message, *args, **_kwargs):
        messages.append(message % args if args else message)

    monkeypatch.setattr(job_discovery_service_module.logger, "warning", capture_warning)
    engine = create_seeded_engine()
    settings = make_settings(tmp_path)
    search_plan = JobSearchPlan(searchMode="broad", roleQueries=["Applied AI Engineer"])

    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        search_run = job_discovery_service_module.create_job_search_run(
            session,
            candidate_profile=profile,
            command_text="Find applied AI engineer jobs to apply to.",
            search_plan=search_plan,
            provider_names=("mock",),
        )
        job_discovery_service_module.log_job_discovery_run_started(
            settings,
            search_run=search_run,
            candidate_profile=profile,
            provider_names=("mock",),
            search_plan=search_plan,
            current_saved_job_count=2,
            current_saved_company_count=3,
        )
        job_discovery_service_module.complete_job_search_run(
            search_run,
            status="completed",
            provider_diagnostics=[],
            total_provider_results=4,
            candidate_pool_count=3,
            model_selected_count=2,
            saved_count=1,
            updated_existing_count=1,
            duplicate_count=1,
            skipped_count=1,
        )
        job_discovery_service_module.log_job_discovery_run_completed(
            search_run=search_run,
            provider_result_count=4,
            candidate_count_after_dedupe=3,
            saved_count=1,
            updated_existing_count=1,
            skipped_count=1,
            provider_error_count=0,
        )

    assert any("Job discovery run started:" in message for message in messages)
    assert any("Job discovery run completed:" in message for message in messages)
    assert any("jobSearchRunId" in message for message in messages)


@SKIP_LEGACY_LIVE_PROVIDER_DISCOVERY
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


def test_provider_url_429_keeps_provider_unverified_without_noisy_summary(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 429, "Too Many Requests", hdrs=None, fp=None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    verification = source_result_verification(
        LiveJobSourceResult(
            title="Studio Assistant",
            company_name="Example Studio",
            job_url="https://provider.example/jobs/studio",
            source_provider="adzuna",
            provenance="provider_result",
            url_verification_summary="Adzuna provider result; URL may redirect through Adzuna.",
        ),
        verify_url=True,
    )

    assert verification.status == "provider_unverified"
    assert verification.expired_or_closed is False
    assert verification.summary == "Adzuna provider result; URL may redirect through Adzuna."
    assert "429" not in verification.summary


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


def test_provider_job_url_does_not_canonicalize_company_by_aggregator_domain() -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        poisoned = Company(
            name="PwC",
            normalized_name="pwc",
            domain="adzuna.com",
            normalized_domain="adzuna.com",
            source_urls=["https://www.adzuna.com/land/ad/old-pwc"],
            source_summary="Legacy provider URL should not be treated as a company domain.",
        )
        session.add(poisoned)
        session.commit()

        result = save_live_job_source_results(
            session,
            candidate_profile=profile,
            discovery_query="broad exploratory job search",
            source_results=[
                LiveJobSourceResult(
                    title="Adjunct Faculty - Visual & Performing Arts",
                    company_name="Graceland University",
                    job_url="https://www.adzuna.com/details/5702208850?utm_medium=api",
                    source_provider="adzuna",
                    source_query="Wheel-throwing",
                    provenance="provider_result",
                    fit_summary="Adjunct professor role specifically for ceramics.",
                )
            ],
            search_queries_used=["Wheel-throwing"],
            provider="adzuna",
            verify_urls=False,
        )
        session.commit()

        assert len(result.added_companies) == 1
        added_company = result.added_companies[0].company
        assert added_company.name == "Graceland University"
        assert added_company.normalized_domain is None
        assert added_company.source_urls == []
        assert result.added_companies[0].personal_source_urls == ["https://www.adzuna.com/details/5702208850?utm_medium=api"]
        assert session.scalar(select(Company).where(Company.name == "PwC")).id == poisoned.id


@SKIP_LEGACY_LIVE_PROVIDER_DISCOVERY
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
                command="Find applied AI engineer jobs to apply to.",
                active_workspace="jobs",
            ),
            session=session,
        )

        assert response.actions[0].type == "job_discovery"
        assert response.actions[0].status == "running"
        assert response.target_workspace == "jobs"
        assert response.result_payload is not None
        assert response.result_payload["async"] is True
        assert response.result_payload["jobSearchRunId"]
        assert response.result_payload["status"] == "queued"
        assert len(session.scalars(select(JobSearchRun)).all()) == 1
        assert len(session.scalars(select(JobPosting)).all()) == 0
        assert len(session.scalars(select(CandidateSavedJob)).all()) == 0


@SKIP_LEGACY_LIVE_PROVIDER_DISCOVERY
def test_job_discovery_returns_clear_error_when_live_source_not_configured(tmp_path: Path) -> None:
    engine = create_seeded_engine()
    settings = make_settings(tmp_path, model_provider="gemini", job_discovery_source="none")

    with Session(engine) as session:
        result = run_job_discovery(
            JobDiscoveryRequest(latest_user_message="Find applied AI engineer jobs for me to apply to.", candidate_profile_slug="rebekah-love"),
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

    def fake_start_job_discovery_run(request: JobDiscoveryRequest, **kwargs):
        captured["client_context"] = request.client_context
        captured["latest_user_message"] = request.latest_user_message
        return (
            SimpleNamespace(
                id="run-with-context",
                status="queued",
                saved_count=0,
                updated_existing_count=0,
                duplicate_count=0,
                skipped_count=0,
                total_provider_results=0,
                model_selected_count=0,
                provider_error_count=0,
            ),
            True,
        )

    monkeypatch.setattr(command_center_module, "start_job_discovery_run", fake_start_job_discovery_run)
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


def test_job_search_planner_request_includes_required_context(tmp_path: Path) -> None:
    request = JobDiscoveryRequest(
        latest_user_message="Find remote applied AI engineer jobs over $130k",
        candidate_profile_slug="rebekah-love",
        active_workspace="jobs",
        router_extracted={"companyName": "Tomoro"},
    )
    model_request = build_job_search_planner_model_request(
        request,
        router_extracted=request.router_extracted,
        current_saved_jobs=[{"title": "Existing Role", "company_name": "Old Co", "normalized_url": "https://old.example/jobs/1"}],
        current_saved_companies=[{"name": "Tomoro", "job_listings_url": "https://tomoro.example/jobs"}],
        target_context={"target_role_titles": ["Applied AI Engineer"]},
        private_profile_context={"profile_basics": {"headline": "Applied AI Systems Engineer"}},
        recent_search_history=[{"command_text": "Find manager jobs", "saved_count": 0}],
        provider_capabilities={"providers": [{"name": "adzuna", "supports_total_matches": True}]},
    )

    payload = json.loads(model_request.messages[-1].content)

    assert model_request.task == "job_search_planning"
    assert model_request.response_mime_type == "application/json"
    assert model_request.search_grounding is False
    assert payload["latest_user_message"] == "Find remote applied AI engineer jobs over $130k"
    assert payload["router_extracted_fields"]["companyName"] == "Tomoro"
    assert payload["candidate_target_context"]["target_role_titles"] == ["Applied AI Engineer"]
    assert payload["private_profile_context"]["profile_basics"]["headline"] == "Applied AI Systems Engineer"
    assert payload["current_saved_companies"][0]["name"] == "Tomoro"
    assert payload["current_saved_jobs_summary"][0]["title"] == "Existing Role"
    assert payload["recent_job_search_history"][0]["command_text"] == "Find manager jobs"
    assert payload["provider_capabilities"]["providers"][0]["name"] == "adzuna"
    assert "Do not invent" in model_request.messages[0].content


def test_search_planner_uses_injected_connector(tmp_path: Path) -> None:
    captured_requests = []

    class FakePlannerConnector:
        def generate(self, request):
            captured_requests.append(request)
            assert request.task == "job_search_planning"
            return fake_job_search_planner_response(
                role_query="Forward Deployed AI Engineer",
                locations=["Connecticut"],
            )

    settings = replace(
        make_settings(tmp_path),
        job_discovery_results_per_provider=50,
        job_discovery_save_limit=25,
    )

    result = select_job_search_plan_with_model(
        JobDiscoveryRequest(
            latest_user_message="Find AI forward deployed engineer jobs in Connecticut.",
            candidate_profile_slug="rebekah-love",
        ),
        connector=FakePlannerConnector(),
        settings=settings,
        router_extracted={},
        current_saved_jobs=[],
        current_saved_companies=[],
        target_context={},
        private_profile_context={},
        recent_search_history=[],
        provider_capabilities={
            "providers": [{"name": "adzuna", "type": "broad_search"}],
            "limits": {"results_per_provider": 50, "max_provider_pages": 2, "replan_limit": 1},
        },
    )

    assert captured_requests
    assert result.fallback_used is False
    assert result.response_provider == "fake"
    assert result.plan.role_queries == ["Forward Deployed AI Engineer"]
    assert result.plan.locations == ["Connecticut"]
    assert result.plan.provider_strategy.requested_result_goal == 50


def test_planner_output_validates_company_salary_location_and_exclusions() -> None:
    output = validate_job_search_planner_output(
        json.dumps(
            {
                "searchPlan": {
                    "searchMode": "company_specific",
                    "roleQueries": ["Senior Applied AI Engineer"],
                    "companyNames": ["Tomoro"],
                    "locations": ["Louisville"],
                    "remoteWorkModes": ["hybrid"],
                    "employmentTypes": ["Full-time"],
                    "salaryMin": 130000,
                    "includeTerms": ["LLM"],
                    "excludeTerms": ["manager", "AI trainer"],
                    "hardConstraints": ["hybrid Louisville", "over $130k"],
                    "softPreferences": ["product engineering"],
                    "providerStrategy": {
                        "useBroadSearch": True,
                        "useCompanyBoards": True,
                        "requestedResultGoal": 30,
                        "maxProviderPages": 2,
                        "allowReplanning": True,
                    },
                    "rationale": "User explicitly asked for a company-specific hybrid Louisville search.",
                }
            }
        )
    )

    plan = output.search_plan
    assert plan.search_mode == "company_specific"
    assert plan.company_names == ["Tomoro"]
    assert plan.locations == ["Louisville"]
    assert plan.remote_work_modes == ["hybrid"]
    assert plan.salary_min == 130000
    assert plan.exclude_terms == ["manager", "AI trainer"]


def test_planner_guardrails_raise_low_provider_goal_to_support_save_limit(tmp_path: Path) -> None:
    settings = replace(
        make_settings(tmp_path),
        job_discovery_results_per_provider=50,
        job_discovery_save_limit=25,
    )
    request = JobDiscoveryRequest(
        latest_user_message="Find AI jobs in Connecticut",
        candidate_profile_slug="rebekah-love",
    )
    plan = JobSearchPlan(
        searchMode="broad",
        roleQueries=["AI Engineer"],
        locations=["Connecticut"],
        providerStrategy={"requestedResultGoal": 20, "maxProviderPages": 2, "allowReplanning": True},
    )
    fallback_plan = build_fallback_job_search_plan(
        request,
        router_extracted={},
        current_saved_companies=[],
        target_context={},
        private_profile_context={},
        settings=settings,
    )

    guarded = apply_job_search_plan_guardrails(
        plan,
        request=request,
        router_extracted={},
        current_saved_companies=[],
        fallback_plan=fallback_plan,
        settings=settings,
    )

    assert guarded.provider_strategy.requested_result_goal == 50


@SKIP_LEGACY_LIVE_PROVIDER_DISCOVERY
def test_job_discovery_persists_search_run_and_query_history(tmp_path: Path) -> None:
    engine = create_seeded_engine()

    with Session(engine) as session:
        result = run_job_discovery(
            JobDiscoveryRequest(
                latest_user_message="Find remote applied AI engineer jobs.",
                candidate_profile_slug="rebekah-love",
            ),
            db_session=session,
            settings=make_settings(tmp_path),
        )

        assert result.status_code == 200
        run = session.scalar(select(JobSearchRun))
        assert run is not None
        assert result.body["result"]["jobSearchRunId"] == run.id
        assert run.status == "completed"
        assert run.command_text == "Find remote applied AI engineer jobs."
        assert run.search_plan_json["roleQueries"]
        assert run.saved_count == result.body["result"]["savedCount"]
        assert run.candidate_pool_count == result.body["result"]["candidateCountAfterDiversityCap"]
        query_runs = session.scalars(select(JobSearchQueryRun)).all()
        assert len(query_runs) == 1
        assert query_runs[0].provider_name == "mock"
        assert query_runs[0].query


@SKIP_LEGACY_LIVE_PROVIDER_DISCOVERY
def test_recent_search_history_is_loaded_into_later_planner_context(tmp_path: Path, monkeypatch) -> None:
    engine = create_seeded_engine()
    captured_payloads: list[dict[str, Any]] = []

    from jobops_api.job_discovery import planning as planning_module

    original = planning_module.build_job_search_planner_model_request

    def capture_request(*args, **kwargs):
        model_request = original(*args, **kwargs)
        captured_payloads.append(json.loads(model_request.messages[-1].content))
        return model_request

    monkeypatch.setattr(planning_module, "build_job_search_planner_model_request", capture_request)

    with Session(engine) as session:
        first = run_job_discovery(
            JobDiscoveryRequest(latest_user_message="Find applied AI engineer jobs.", candidate_profile_slug="rebekah-love"),
            db_session=session,
            settings=make_settings(tmp_path),
        )
        assert first.status_code == 200
        second = run_job_discovery(
            JobDiscoveryRequest(latest_user_message="Try something broader.", candidate_profile_slug="rebekah-love"),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    assert second.status_code == 200
    assert captured_payloads[0]["recent_job_search_history"] == []
    assert captured_payloads[1]["recent_job_search_history"][0]["command_text"] == "Find applied AI engineer jobs."
    assert captured_payloads[1]["recent_job_search_history"][0]["saved_count"] == 2


@SKIP_LEGACY_LIVE_PROVIDER_DISCOVERY
def test_company_specific_job_discovery_preserves_explicit_company(tmp_path: Path) -> None:
    engine = create_seeded_engine()

    with Session(engine) as session:
        result = run_job_discovery(
            JobDiscoveryRequest(
                latest_user_message="Check for relevant jobs at Tomoro.",
                candidate_profile_slug="rebekah-love",
                router_extracted={"companyName": "Tomoro"},
            ),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    assert result.status_code == 200
    assert result.body["result"]["searchPlan"]["searchMode"] == "company_specific"
    assert result.body["result"]["searchPlan"]["companyNames"] == ["Tomoro"]
    assert all("Tomoro" in query for query in result.body["result"]["searchQueriesUsed"])


@SKIP_LEGACY_LIVE_PROVIDER_DISCOVERY
def test_followed_company_job_discovery_uses_saved_companies(tmp_path: Path) -> None:
    engine = create_seeded_engine()

    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        add_saved_company(session, profile.id, "Tomoro")
        add_saved_company(session, profile.id, "Wasteology")
        session.commit()

        result = run_job_discovery(
            JobDiscoveryRequest(
                latest_user_message="Find jobs from my companies list.",
                candidate_profile_slug="rebekah-love",
            ),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    assert result.status_code == 200
    assert result.body["result"]["searchPlan"]["searchMode"] == "followed_companies"
    assert set(result.body["result"]["searchPlan"]["companyNames"][:2]) == {"Wasteology", "Tomoro"}
    assert any("Tomoro" in query for query in result.body["result"]["searchQueriesUsed"])
    assert any("Wasteology" in query for query in result.body["result"]["searchQueriesUsed"])


def test_adzuna_paginates_when_total_matches_indicates_more_results(monkeypatch, tmp_path: Path) -> None:
    requested_urls: list[str] = []

    class FakeResponse:
        status = 200
        headers = {"content-type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, *_args):
            page = len(requested_urls)
            return json.dumps(
                {
                    "count": 25,
                    "results": [
                        {
                            "id": f"adz-{page}",
                            "title": f"Applied AI Engineer {page}",
                            "company": {"display_name": "Provider Co"},
                            "redirect_url": f"https://jobs.example.test/{page}",
                            "description": "Applied AI role",
                        }
                    ],
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        requested_urls.append(request.full_url)
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    from jobops_api.job_discovery.providers.adzuna import AdzunaJobDiscoveryProvider

    provider = AdzunaJobDiscoveryProvider()
    settings = make_settings(
        tmp_path,
        model_provider="mock",
        job_discovery_source="none",
        job_discovery_providers=("adzuna",),
        adzuna_app_id="app-id",
        adzuna_app_key="app-key",
    )
    outcome = provider.search(
        JobSearchRequest(
            latest_user_message="Find applied AI jobs.",
            search_queries=["Applied AI Engineer"],
            results_per_provider=10,
            current_saved_companies=[],
            target_context={},
            private_profile_context={},
            user_constraints=[],
            max_provider_pages=2,
        ),
        settings,
    )

    assert len(outcome.results) == 2
    assert [diagnostic.page for diagnostic in outcome.diagnostics] == [1, 2]
    assert all(diagnostic.total_matches == 25 for diagnostic in outcome.diagnostics)
    assert outcome.diagnostics[0].request_criteria == {
        "country": "us",
        "page": 1,
        "what": "Applied AI Engineer",
        "where": None,
        "whatExclude": None,
        "resultsPerPage": 10,
        "contentType": "application/json",
    }
    assert requested_urls[0].split("?")[0].endswith("/search/1")
    assert requested_urls[1].split("?")[0].endswith("/search/2")


def test_adzuna_does_not_paginate_zero_total_matches(monkeypatch, tmp_path: Path) -> None:
    requested_urls: list[str] = []

    class FakeResponse:
        status = 200
        headers = {"content-type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, *_args):
            return json.dumps({"count": 0, "results": []}).encode("utf-8")

    def fake_urlopen(request, timeout):
        requested_urls.append(request.full_url)
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    from jobops_api.job_discovery.providers.adzuna import AdzunaJobDiscoveryProvider

    provider = AdzunaJobDiscoveryProvider()
    settings = make_settings(
        tmp_path,
        model_provider="mock",
        job_discovery_source="none",
        job_discovery_providers=("adzuna",),
        adzuna_app_id="app-id",
        adzuna_app_key="app-key",
    )
    outcome = provider.search(
        JobSearchRequest(
            latest_user_message="Find applied AI jobs.",
            search_queries=["Applied AI Engineer"],
            results_per_provider=10,
            current_saved_companies=[],
            target_context={},
            private_profile_context={},
            user_constraints=[],
            max_provider_pages=3,
        ),
        settings,
    )

    assert outcome.results == []
    assert len(requested_urls) == 1
    assert outcome.diagnostics[0].total_matches == 0
    assert outcome.diagnostics[0].page == 1



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


def add_saved_company(session: Session, candidate_profile_id: str, name: str) -> CandidateCompany:
    company = Company(
        name=name,
        normalized_name=name.casefold(),
        source_summary="Test saved company.",
    )
    session.add(company)
    session.flush()
    link = CandidateCompany(
        candidate_profile_id=candidate_profile_id,
        company_id=company.id,
        review_status="new",
        derivation_status="model_derived",
    )
    session.add(link)
    session.flush()
    return link


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
