from __future__ import annotations

import json
import time
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

import jobops_api.job_discovery.candidate_discovery.planner as planner_module
import jobops_api.job_discovery.candidate_discovery.service as candidate_service_module
from jobops_api.db.models import CandidateCompany, Company, JobListing, JobListingSource, JobSearchQueryRun, JobSyncRun, JobSyncSignature
from jobops_api.job_discovery.candidate_discovery.models import (
    DbJobSearchPlan,
    DbJobSearchQuery,
    JobReviewResult,
    ReviewPlan,
    RejectedJobDecision,
    SelectedJobDecision,
)
from jobops_api.job_discovery.candidate_discovery.diagnostics import build_candidate_discovery_diagnostics, format_candidate_discovery_diagnostics
from jobops_api.job_discovery.candidate_discovery.planner import DbJobSearchPlanner, DbJobSearchPlanningError, parse_db_search_plan
from jobops_api.job_discovery.candidate_discovery.prompts import DB_JOB_SEARCH_PLAN_CRITIC_SYSTEM_PROMPT, DB_JOB_SEARCH_PLANNER_SYSTEM_PROMPT
from jobops_api.job_discovery.candidate_discovery.query_builder import JobListingQueryBuilder
from jobops_api.job_discovery.candidate_discovery.repositories import CandidateJobRepository, ModelRejectionService
from jobops_api.job_discovery.candidate_discovery.reviewer import JobReviewSelector, validate_review_result
from jobops_api.job_discovery.candidate_discovery.service import CandidateJobDiscoveryService, build_theirstack_provider_consideration
from jobops_api.job_discovery.models import JobDiscoveryRequest
from jobops_api.job_discovery.service import build_db_backed_job_discovery_result, list_jobs, serialize_job_search_run_status
from jobops_api.job_discovery.job_sync.models import JobSyncRequest, JobSyncResult
from jobops_api.job_discovery.job_sync.service import record_job_sync_run
from jobops_api.db.models import Application, CandidateJobRejectionReason, CandidateSavedJob, JobSearchRun

from test_candidate_job_discovery import (
    NoSyncCandidateJobDiscoveryService,
    StaticPlanner,
    create_candidate_discovery_engine,
    create_candidate_profile,
    create_job_listing,
    make_settings,
)


def test_deterministic_scope_inference_helpers_are_removed() -> None:
    for name in (
        "infer_scope",
        "is_existing_jobs_list_request",
        "is_new_job_discovery_request",
        "is_all_accessible_jobs_request",
        "phrase_matches",
    ):
        assert not hasattr(planner_module, name)


def test_planner_prompt_contains_broadening_and_override_instructions() -> None:
    prompt = DB_JOB_SEARCH_PLANNER_SYSTEM_PROMPT

    assert "To broaden a search and increase results, remove or relax criteria" in prompt
    assert "Explicit latest-thread constraints outrank stored profile defaults" in prompt
    assert "Ask the user only before relaxing an explicit" in prompt
    assert "You choose the discovery mode" in prompt
    assert "plan inventory refresh sync tokens" in prompt
    assert "Find me some jobs to apply to." in prompt
    assert "Find jobs from my companies list." in prompt
    assert "syncPlan.useFollowedCompanyBoards=true" in prompt
    assert 'sourceProvidersAny=["greenhouse","ashby"]' in prompt
    assert "missing_followed_company_board_sync" in DB_JOB_SEARCH_PLAN_CRITIC_SYSTEM_PROMPT
    assert "new_job_discovery" in prompt
    assert "Do not call job results \"candidates.\"" in prompt
    assert "For model-grounded discovery, you must ground recommendations in fresh provider or web search results from this run" in prompt
    assert "Prefer TheirStack for fresh" in prompt
    assert "company hiring/job discovery when available" in prompt
    assert "If no fresh source confirms the job is currently" in prompt
    assert "available, do not save it" in prompt
    assert "Return JSON only" in DB_JOB_SEARCH_PLAN_CRITIC_SYSTEM_PROMPT
    assert "correctedPlan" in DB_JOB_SEARCH_PLAN_CRITIC_SYSTEM_PROMPT
    assert "prior model knowledge, or stale history" in DB_JOB_SEARCH_PLAN_CRITIC_SYSTEM_PROMPT


def test_db_planner_without_connector_fails_without_deterministic_terms(tmp_path) -> None:
    with pytest.raises(DbJobSearchPlanningError) as exc:
        DbJobSearchPlanner().plan(
            JobDiscoveryRequest(latest_user_message="Find Python AI jobs.", candidate_profile_slug="rebekah-love"),
            connector=None,
            settings=make_settings(tmp_path),
            current_saved_jobs=[],
            current_saved_companies=[],
            target_context={},
            private_profile_context={},
        )

    assert exc.value.diagnostics["planner"]["planningFailed"] is True
    assert not hasattr(planner_module, "deterministic_plan_from_request")
    assert not hasattr(planner_module, "extract_search_terms")


def test_db_planner_connector_exception_does_not_generate_search_terms(tmp_path) -> None:
    class FailingConnector:
        def generate(self, request):
            raise RuntimeError("model down")

    with pytest.raises(DbJobSearchPlanningError) as exc:
        DbJobSearchPlanner().plan(
            JobDiscoveryRequest(latest_user_message="Find Python AI jobs.", candidate_profile_slug="rebekah-love"),
            connector=FailingConnector(),
            settings=make_settings(tmp_path),
            current_saved_jobs=[],
            current_saved_companies=[],
            target_context={},
            private_profile_context={},
        )

    assert exc.value.diagnostics["planner"]["planningFailed"] is True
    assert "Python" not in str(exc.value.diagnostics)


def test_db_planner_connector_timeout_fails_loudly(tmp_path) -> None:
    class SlowConnector:
        def generate(self, request):
            time.sleep(0.2)
            raise AssertionError("Planner should stop waiting before this returns.")

    settings = replace(make_settings(tmp_path), llm_request_timeout_seconds=0.01)

    with pytest.raises(DbJobSearchPlanningError) as exc:
        DbJobSearchPlanner().plan(
            JobDiscoveryRequest(latest_user_message="Find Python AI jobs.", candidate_profile_slug="rebekah-love"),
            connector=SlowConnector(),
            settings=settings,
            current_saved_jobs=[],
            current_saved_companies=[],
            target_context={},
            private_profile_context={},
        )

    assert exc.value.diagnostics["planner"]["planningFailed"] is True
    assert exc.value.diagnostics["planner"]["error"] == "TimeoutError"
    assert "timeout" in exc.value.diagnostics["planner"]["errorDetail"]
    assert "Python" not in str(exc.value.diagnostics)


def test_db_planner_missing_queries_is_planning_failure() -> None:
    with pytest.raises(DbJobSearchPlanningError):
        parse_db_search_plan(
            json.dumps(
                {
                    "mode": "new_job_discovery",
                    "syncPlan": {"useFollowedCompanyBoards": False, "proposedAdzunaSignatures": [], "existingAdzunaSignatureIdsToRefresh": []},
                    "dbSearchPlan": {"queries": []},
                }
            )
        )


def test_reset_all_model_rejections_uses_hidden_reviewable_status() -> None:
    engine = create_candidate_discovery_engine()
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        job = create_job_listing(session, title="Growth Product Manager", provider_job_id="reset-all")
        CandidateJobRepository(session).apply_review_result(
            candidate_profile_id=profile.id,
            job_search_run_id=None,
            review=JobReviewResult(
                user_visible_summary="Rejected.",
                rejected_jobs=(
                    RejectedJobDecision(
                        job_listing_id=job.id,
                        reason_codes=("industry_or_domain", "location"),
                        explanation="Wrong industry and location.",
                    ),
                ),
            ),
        )
        session.commit()

        reset_count = ModelRejectionService(session).reset_model_rejections(candidate_profile_id=profile.id)
        session.commit()

        link = session.scalar(select(CandidateSavedJob).where(CandidateSavedJob.job_listing_id == job.id))
        assert link is not None
        assert reset_count == 2
        assert link.status == "model_rejection_reset"
        assert link.model_rejected_at is None
        assert all(not reason.active for reason in link.rejection_reasons)


def test_reset_one_reason_keeps_model_rejected_when_active_reason_remains() -> None:
    engine = create_candidate_discovery_engine()
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        job = create_job_listing(session, title="Backend Engineer", provider_job_id="reset-one")
        CandidateJobRepository(session).apply_review_result(
            candidate_profile_id=profile.id,
            job_search_run_id=None,
            review=JobReviewResult(
                user_visible_summary="Rejected.",
                rejected_jobs=(
                    RejectedJobDecision(
                        job_listing_id=job.id,
                        reason_codes=("location", "role_title"),
                        explanation="Wrong location and title.",
                    ),
                ),
            ),
        )
        session.commit()

        reset_count = ModelRejectionService(session).reset_model_rejections(
            candidate_profile_id=profile.id,
            reason_codes=["location"],
        )
        session.commit()

        link = session.scalar(select(CandidateSavedJob).where(CandidateSavedJob.job_listing_id == job.id))
        assert link is not None
        assert reset_count == 1
        assert link.status == "model_rejected"
        assert {reason.reason_code for reason in link.rejection_reasons if reason.active} == {"role_title"}


def test_normal_jobs_list_excludes_hidden_rejection_statuses() -> None:
    engine = create_candidate_discovery_engine()
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        visible = create_job_listing(session, title="AI Engineer", provider_job_id="visible")
        rejected = create_job_listing(session, title="Rejected Job", provider_job_id="hidden-rejected")
        reset = create_job_listing(session, title="Reset Job", provider_job_id="hidden-reset")
        session.add_all(
            [
                CandidateSavedJob(candidate_profile_id=profile.id, job_listing_id=visible.id, status="new"),
                CandidateSavedJob(candidate_profile_id=profile.id, job_listing_id=rejected.id, status="model_rejected"),
                CandidateSavedJob(candidate_profile_id=profile.id, job_listing_id=reset.id, status="model_rejection_reset"),
            ]
        )
        session.commit()

        rows = list_jobs(session=session, auth=SimpleNamespace(candidate_profile=profile))

    assert [row["title"] for row in rows] == ["AI Engineer"]


def test_query_builder_new_to_candidate_includes_reset_but_excludes_active_rejected() -> None:
    engine = create_candidate_discovery_engine()
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        visible = create_job_listing(session, title="Already Visible", provider_job_id="visible-block")
        rejected = create_job_listing(session, title="Active Rejected", provider_job_id="active-rejected")
        reset = create_job_listing(session, title="Reviewable Reset", provider_job_id="reviewable-reset")
        session.add_all(
            [
                CandidateSavedJob(candidate_profile_id=profile.id, job_listing_id=visible.id, status="new"),
                CandidateSavedJob(candidate_profile_id=profile.id, job_listing_id=rejected.id, status="model_rejected"),
                CandidateSavedJob(candidate_profile_id=profile.id, job_listing_id=reset.id, status="model_rejection_reset"),
            ]
        )
        session.commit()

        jobs, _ = JobListingQueryBuilder(session).execute_plan(
            profile.id,
            DbJobSearchPlan(
                job_scope="new_to_candidate",
                queries=(DbJobSearchQuery(source_statuses_any=("active",), limit=10),),
            ),
        )

    assert {job.id for job in jobs} == {reset.id}


def test_candidate_jobs_list_excludes_hidden_statuses_by_default() -> None:
    engine = create_candidate_discovery_engine()
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        visible = create_job_listing(session, title="Visible", provider_job_id="list-visible")
        rejected = create_job_listing(session, title="Rejected", provider_job_id="list-rejected")
        reset = create_job_listing(session, title="Reset", provider_job_id="list-reset")
        session.add_all(
            [
                CandidateSavedJob(candidate_profile_id=profile.id, job_listing_id=visible.id, status="saved"),
                CandidateSavedJob(candidate_profile_id=profile.id, job_listing_id=rejected.id, status="model_rejected"),
                CandidateSavedJob(candidate_profile_id=profile.id, job_listing_id=reset.id, status="model_rejection_reset"),
            ]
        )
        session.commit()

        jobs, _ = JobListingQueryBuilder(session).execute_plan(
            profile.id,
            DbJobSearchPlan(
                job_scope="candidate_jobs_list",
                queries=(DbJobSearchQuery(source_statuses_any=("active",), limit=10),),
            ),
        )

    assert {job.id for job in jobs} == {visible.id}


def test_reviewer_without_connector_returns_no_selected_jobs(tmp_path) -> None:
    result = JobReviewSelector().review(
        JobDiscoveryRequest(latest_user_message="Find jobs.", candidate_profile_slug="rebekah-love"),
        connector=None,
        settings=make_settings(tmp_path),
        job_pool=[],
        max_selected=10,
    )

    assert result.selected_jobs == ()
    assert result.rejected_jobs == ()
    assert result.diagnostics["modelReviewFallback"] is True


def test_reviewer_connector_exception_returns_no_selected_jobs(tmp_path) -> None:
    class FailingConnector:
        def generate(self, request):
            raise RuntimeError("model unavailable")

    job = SimpleNamespace(
        job_listing_id="job-1",
        title="AI Engineer",
        company_name="Example",
        location_display="Remote",
        remote_work_mode="remote",
        employment_type="full_time",
        salary_text=None,
        description_excerpt="Build AI systems.",
        source_providers=("greenhouse",),
    )

    result = JobReviewSelector().review(
        JobDiscoveryRequest(latest_user_message="Find jobs.", candidate_profile_slug="rebekah-love"),
        connector=FailingConnector(),
        settings=make_settings(tmp_path),
        job_pool=[job],
        max_selected=10,
    )

    assert result.selected_jobs == ()
    assert result.rejected_jobs == ()
    assert result.diagnostics["modelReviewFallback"] is True
    assert result.user_visible_summary.startswith("I found synced jobs to review")


def test_reviewer_retries_invalid_json_and_uses_valid_retry(tmp_path) -> None:
    class InvalidThenValidConnector:
        def __init__(self) -> None:
            self.calls = 0
            self.requests = []

        def generate(self, request):
            self.calls += 1
            self.requests.append(request)
            if self.calls == 1:
                return SimpleNamespace(text='{"userVisibleSummary": "truncated"', finish_reason="MAX_TOKENS")
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "userVisibleSummary": "I found one strong job.",
                        "selectedJobs": [{"jobListingId": "job-1", "rationale": "Strong match.", "matchHighlights": ["AI platform"]}],
                        "rejectedJobs": [],
                        "criteriaAdjustmentSuggestion": {"shouldAskUser": False, "message": None, "criteriaToRelax": []},
                    }
                ),
                finish_reason="stop",
            )

    connector = InvalidThenValidConnector()
    job = SimpleNamespace(
        job_listing_id="job-1",
        title="AI Engineer",
        company_name="Example",
        location_display="Remote",
        remote_work_mode="remote",
        employment_type="full_time",
        salary_text=None,
        description_excerpt="Build AI systems.",
        source_providers=("adzuna",),
    )

    result = JobReviewSelector().review(
        JobDiscoveryRequest(latest_user_message="Find jobs.", candidate_profile_slug="rebekah-love"),
        connector=connector,
        settings=make_settings(tmp_path),
        job_pool=[job],
        max_selected=10,
    )

    assert connector.calls == 2
    first_payload = json.loads(connector.requests[0].messages[-1].content)
    retry_instruction = connector.requests[1].messages[-1].content
    assert "maxRejectedJobs" not in first_payload
    assert "Do not include every unselected job" not in " ".join(first_payload["outputRules"])
    assert connector.requests[0].max_output_tokens == 32000
    assert "Respect maxSelectedJobs." in retry_instruction
    assert [decision.job_listing_id for decision in result.selected_jobs] == ["job-1"]
    assert result.diagnostics["modelReviewCompleted"] is True
    assert result.diagnostics["modelReviewRetried"] is True
    assert result.diagnostics["modelReviewAttemptCount"] == 2


def test_reviewer_invalid_json_after_retry_returns_no_selected_jobs(tmp_path) -> None:
    class AlwaysInvalidConnector:
        def generate(self, request):
            return SimpleNamespace(text='{"userVisibleSummary": "still truncated"', finish_reason="MAX_TOKENS")

    job = SimpleNamespace(
        job_listing_id="job-1",
        title="AI Engineer",
        company_name="Example",
        location_display="Remote",
        remote_work_mode="remote",
        employment_type="full_time",
        salary_text=None,
        description_excerpt="Build AI systems.",
        source_providers=("adzuna",),
    )

    result = JobReviewSelector().review(
        JobDiscoveryRequest(latest_user_message="Find jobs.", candidate_profile_slug="rebekah-love"),
        connector=AlwaysInvalidConnector(),
        settings=make_settings(tmp_path),
        job_pool=[job],
        max_selected=10,
    )

    assert result.selected_jobs == ()
    assert result.rejected_jobs == ()
    assert result.diagnostics["modelReviewFallback"] is True
    assert result.diagnostics["modelReviewFailureReason"].startswith("model_review_invalid_json:")
    assert result.diagnostics["modelReviewAttemptCount"] == 2
    assert result.diagnostics["debugInvalidReviewAttempt"] == 2
    assert result.diagnostics["debugInvalidReviewFinishReason"] == "MAX_TOKENS"
    assert result.diagnostics["debugInvalidReviewResponseLength"] == len('{"userVisibleSummary": "still truncated"')
    assert "still truncated" in result.diagnostics["debugInvalidReviewResponsePreview"]


def test_reviewer_request_does_not_cap_rejected_jobs_for_large_pool(tmp_path) -> None:
    selector = JobReviewSelector()
    request = selector.build_model_request(
        JobDiscoveryRequest(latest_user_message="Find jobs.", candidate_profile_slug="rebekah-love"),
        job_pool=[
            SimpleNamespace(
                job_listing_id=f"job-{index}",
                title=f"Job {index}",
                company_name="Example",
                location_display="Remote",
                remote_work_mode="remote",
                employment_type="full_time",
                salary_text=None,
                description_excerpt="Build systems.",
                source_providers=("adzuna",),
            )
            for index in range(66)
        ],
        max_selected=25,
    )

    payload = json.loads(request.messages[-1].content)
    assert "maxRejectedJobs" not in payload
    assert request.max_output_tokens == 32000
    assert "Do not include every unselected job" not in " ".join(payload["outputRules"])


def test_reviewer_invalid_json_debug_preview_is_not_persisted_in_prod(tmp_path) -> None:
    class AlwaysInvalidConnector:
        def generate(self, request):
            return SimpleNamespace(text='{"userVisibleSummary": "prod truncated"', finish_reason="MAX_TOKENS")

    job = SimpleNamespace(
        job_listing_id="job-1",
        title="AI Engineer",
        company_name="Example",
        location_display="Remote",
        remote_work_mode="remote",
        employment_type="full_time",
        salary_text=None,
        description_excerpt="Build AI systems.",
        source_providers=("adzuna",),
    )

    result = JobReviewSelector().review(
        JobDiscoveryRequest(latest_user_message="Find jobs.", candidate_profile_slug="rebekah-love"),
        connector=AlwaysInvalidConnector(),
        settings=replace(make_settings(tmp_path), app_env="prod"),
        job_pool=[job],
        max_selected=10,
    )

    assert result.diagnostics["modelReviewFailureReason"].startswith("model_review_invalid_json:")
    assert "debugInvalidReviewResponsePreview" not in result.diagnostics


def test_service_model_failure_does_not_create_candidate_job_rows(tmp_path) -> None:
    class FailingConnector:
        def generate(self, request):
            raise RuntimeError("model unavailable")

    engine = create_candidate_discovery_engine()
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        create_job_listing(session, title="AI Platform Engineer", provider_job_id="model-fail")
        session.commit()

        service = NoSyncCandidateJobDiscoveryService(
            session=session,
            settings=make_settings(tmp_path),
            connector=FailingConnector(),
            planner=StaticPlanner(),
        )
        result = service.run(
            JobDiscoveryRequest(latest_user_message="Find jobs.", candidate_profile_slug=profile.slug),
            candidate_profile=profile,
            current_saved_jobs=[],
            current_saved_companies=[],
            target_context={},
            private_profile_context={},
        )
        session.commit()

        rows = list(session.scalars(select(CandidateSavedJob)).all())

    assert rows == []
    assert result.unique_job_pool_count == 1
    assert result.added_count == 0
    assert result.rejected_count == 0
    assert result.diagnostics["modelReview"]["modelReviewFallback"] is True


def test_service_planning_failure_runs_no_sync_query_review_or_writes(tmp_path) -> None:
    engine = create_candidate_discovery_engine()
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        create_job_listing(session, title="AI Platform Engineer", provider_job_id="planning-fail-existing")
        session.commit()

        service = CandidateJobDiscoveryService(
            session=session,
            settings=make_settings(tmp_path),
            connector=None,
        )
        result = service.run(
            JobDiscoveryRequest(latest_user_message="Find AI platform jobs.", candidate_profile_slug=profile.slug),
            candidate_profile=profile,
            current_saved_jobs=[],
            current_saved_companies=[],
            target_context={},
            private_profile_context={},
        )
        session.commit()

        rows = list(session.scalars(select(CandidateSavedJob)).all())
        sync_runs = list(session.scalars(select(JobSyncRun)).all())
        run = session.get(JobSearchRun, result.job_search_run_id)

    assert rows == []
    assert sync_runs == []
    assert run is not None
    assert run.status == "failed"
    assert run.error == "Model search planning did not complete."
    assert result.diagnostics["planner"]["planningFailed"] is True
    assert result.diagnostics["noJobsAddedReason"] == "model_planning_failed"
    assert result.unique_job_pool_count == 0


def test_model_planned_adzuna_signature_syncs_before_db_query_and_records_diagnostics(tmp_path, monkeypatch) -> None:
    engine = create_candidate_discovery_engine()
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        monkeypatch.setattr(candidate_service_module, "sync_greenhouse_boards", lambda *args, **kwargs: ())

        def fake_sync_adzuna_signatures(session_arg, *, settings, signature_ids=None, enabled_only=True, force=False, **kwargs):
            assert signature_ids
            signature = session_arg.get(JobSyncSignature, signature_ids[0])
            assert signature is not None
            job = create_job_listing(session_arg, title="AI Sync Created Engineer", provider="adzuna", provider_job_id="synced-before-query")
            request = JobSyncRequest(
                sync_key=signature.sync_key,
                provider_name="adzuna",
                provider_type="broad_search",
                sync_kind="broad_search",
                job_sync_signature_id=signature.id,
                provider_country=signature.provider_country,
                provider_where=signature.provider_where,
                display_location=signature.display_location,
                query_text=signature.query_text,
                query_kind=signature.query_kind,
                criteria_json=signature.criteria_json,
            )
            result = JobSyncResult(request=request, raw_result_count=1, normalized_count=1, created_count=1)
            record_job_sync_run(session_arg, result)
            assert job.id
            return [result]

        monkeypatch.setattr(candidate_service_module, "sync_adzuna_signatures", fake_sync_adzuna_signatures)
        service = CandidateJobDiscoveryService(
            session=session,
            settings=make_settings(tmp_path),
            planner=ProposedAdzunaPlanner(),
            reviewer=SelectFirstReviewer(),
        )
        result = service.run(
            JobDiscoveryRequest(latest_user_message="Find AI jobs in Remote US.", candidate_profile_slug=profile.slug),
            candidate_profile=profile,
            current_saved_jobs=[],
            current_saved_companies=[],
            target_context={},
            private_profile_context={},
        )
        session.commit()

        signatures = list(session.scalars(select(JobSyncSignature)).all())
        sync_runs = list(session.scalars(select(JobSyncRun)).all())
        saved_rows = list(session.scalars(select(CandidateSavedJob)).all())

    assert len(signatures) == 1
    assert signatures[0].query_text == "AI"
    assert len(sync_runs) == 1
    assert sync_runs[0].sync_key == signatures[0].sync_key
    assert result.added_count == 1
    assert saved_rows[0].job_search_run_id == result.job_search_run_id
    planned = result.diagnostics["planner"]["plannedSyncSignatures"][0]
    assert planned["syncKey"] == signatures[0].sync_key
    assert planned["queryText"] == "AI"
    assert planned["displayLocation"] == "Remote US"
    assert planned["providerCountry"] == "us"
    assert planned["maxPages"] == 1
    assert planned["resultsPerPage"] == 50
    assert result.diagnostics["databaseQueries"]["queries"][0]["jobCount"] == 1


def test_model_critic_corrects_new_discovery_plan_that_reviews_empty_jobs_list(tmp_path, monkeypatch) -> None:
    engine = create_candidate_discovery_engine()
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        monkeypatch.setattr(candidate_service_module, "sync_greenhouse_boards", lambda *args, **kwargs: ())

        def fake_sync_adzuna_signatures(session_arg, *, settings, signature_ids=None, enabled_only=True, force=False, **kwargs):
            signature = session_arg.get(JobSyncSignature, signature_ids[0])
            assert signature is not None
            create_job_listing(session_arg, title="AI Sync Corrected Engineer", provider="adzuna", provider_job_id="critic-corrected")
            result = JobSyncResult(
                request=JobSyncRequest(
                    sync_key=signature.sync_key,
                    provider_name="adzuna",
                    provider_type="broad_search",
                    sync_kind="broad_search",
                    job_sync_signature_id=signature.id,
                    provider_country=signature.provider_country,
                    provider_where=signature.provider_where,
                    display_location=signature.display_location,
                    query_text=signature.query_text,
                    query_kind=signature.query_kind,
                    criteria_json=signature.criteria_json,
                ),
                raw_result_count=1,
                normalized_count=1,
                created_count=1,
            )
            record_job_sync_run(session_arg, result)
            return [result]

        monkeypatch.setattr(candidate_service_module, "sync_adzuna_signatures", fake_sync_adzuna_signatures)
        service = CandidateJobDiscoveryService(
            session=session,
            settings=replace(make_settings(tmp_path), job_discovery_save_limit=1),
            connector=CriticCorrectsConnector(),
            reviewer=SelectFirstReviewer(),
        )

        result = service.run(
            JobDiscoveryRequest(latest_user_message="Find me some jobs to apply to.", candidate_profile_slug=profile.slug),
            candidate_profile=profile,
            current_saved_jobs=[],
            current_saved_companies=[],
            target_context={},
            private_profile_context={},
        )
        session.commit()

        query_runs = list(session.scalars(select(JobSearchQueryRun)).all())

    assert result.search_plan.mode == "new_job_discovery"
    assert result.search_plan.job_scope == "new_to_candidate"
    assert result.search_plan.proposed_adzuna_signatures
    assert result.diagnostics["planner"]["criticAttemptCount"] == 1
    assert result.diagnostics["planner"]["rejectedPlans"][0]["issueCode"] == "mode_mismatch"
    assert result.diagnostics["planner"]["mode"] == "new_job_discovery"
    assert result.diagnostics["planner"]["plannedSyncSignatures"][0]["queryText"] == "AI"
    assert result.added_count == 1
    assert len(query_runs) >= 1
    assert query_runs[-1].provider_name == "database"
    assert query_runs[-1].raw_result_count == 1


def test_jobs_list_review_does_not_sync_when_model_does_not_plan_sync(tmp_path, monkeypatch) -> None:
    engine = create_candidate_discovery_engine()
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        job = create_job_listing(session, title="Existing AI Job", provider_job_id="existing-list-review")
        session.add(CandidateSavedJob(candidate_profile_id=profile.id, job_listing_id=job.id, status="saved"))
        session.commit()

        sync_called = False

        def fake_sync(*args, **kwargs):
            nonlocal sync_called
            sync_called = True
            return []

        monkeypatch.setattr(candidate_service_module, "sync_greenhouse_boards", fake_sync)
        monkeypatch.setattr(candidate_service_module, "sync_ashby_boards", fake_sync)
        monkeypatch.setattr(candidate_service_module, "sync_adzuna_signatures", fake_sync)
        service = CandidateJobDiscoveryService(
            session=session,
            settings=make_settings(tmp_path),
            connector=JobsListReviewConnector(),
            reviewer=SelectFirstReviewer(),
        )

        result = service.run(
            JobDiscoveryRequest(latest_user_message="Which jobs should I apply to first?", candidate_profile_slug=profile.slug),
            candidate_profile=profile,
            current_saved_jobs=[{"title": "Existing AI Job"}],
            current_saved_companies=[],
            target_context={},
            private_profile_context={},
        )
        session.commit()

    assert sync_called is False
    assert result.search_plan.mode == "jobs_list_review"
    assert result.search_plan.job_scope == "candidate_jobs_list"
    assert result.unique_job_pool_count == 1


def test_followed_company_job_discovery_syncs_supported_ats_boards_and_saves_jobs(tmp_path, monkeypatch) -> None:
    engine = create_candidate_discovery_engine()
    synced_greenhouse_tokens: list[str] = []
    synced_ashby_profiles: list[str] = []

    def fake_sync_greenhouse_boards(session_arg, **kwargs):
        assert kwargs["candidate_profile_id"] == profile.id
        assert kwargs["include_configured"] is False
        rows = session_arg.execute(
            select(CandidateCompany, Company)
            .join(Company, Company.id == CandidateCompany.company_id)
            .where(CandidateCompany.candidate_profile_id == kwargs["candidate_profile_id"])
        ).all()
        results = []
        for _link, company in rows:
            token = company.greenhouse_board_token
            if not token:
                continue
            synced_greenhouse_tokens.append(token)
            now = datetime.now(UTC)
            listing = JobListing(
                title=f"{company.name} Product Marketing Manager",
                company_id=company.id,
                company_name=company.name,
                canonical_url=f"https://job-boards.greenhouse.io/{token}/jobs/1",
                apply_url=f"https://job-boards.greenhouse.io/{token}/jobs/1",
                source_url=f"https://job-boards.greenhouse.io/{token}/jobs/1",
                location_display="Remote US",
                location_country="us",
                remote_work_mode="remote",
                employment_type="full_time",
                description_excerpt=f"{company.name} product marketing role.",
                source_status="active",
                is_active=True,
                first_seen_at=now,
                last_seen_at=now,
                source_updated_at=now,
                last_synced_at=now,
            )
            source = JobListingSource(
                job_listing=listing,
                source_provider="greenhouse",
                provider_type="ats_board",
                provider_job_id=f"{token}-1",
                source_result_id=f"{token}-1",
                ats_provider="greenhouse",
                ats_board_token=token,
                source_url=listing.source_url,
                apply_url=listing.apply_url,
                canonical_url=listing.canonical_url,
                raw_metadata_json={"provider": "greenhouse"},
                is_active=True,
                first_seen_at=now,
                last_seen_at=now,
                last_synced_at=now,
            )
            session_arg.add(source)
            session_arg.flush()
            results.append(
                JobSyncResult(
                    request=JobSyncRequest(
                        sync_key=f"greenhouse:{token}",
                        provider_name="greenhouse",
                        provider_type="ats_board",
                        sync_kind="company_board",
                        company_id=company.id,
                        company_name=company.name,
                        ats_provider="greenhouse",
                        ats_board_token=token,
                    ),
                    raw_result_count=1,
                    normalized_count=1,
                    created_count=1,
                )
            )
        return results

    def fake_sync_ashby_boards(session_arg, **kwargs):
        assert kwargs["candidate_profile_id"] == profile.id
        assert kwargs["include_configured"] is False
        synced_ashby_profiles.append(kwargs["candidate_profile_id"])
        rows = session_arg.execute(
            select(CandidateCompany, Company)
            .join(Company, Company.id == CandidateCompany.company_id)
            .where(CandidateCompany.candidate_profile_id == kwargs["candidate_profile_id"])
        ).all()
        results = []
        for _link, company in rows:
            if not company.ashby_board_url:
                continue
            token = company.ashby_board_url.rstrip("/").split("/")[-1]
            now = datetime.now(UTC)
            listing = JobListing(
                title=f"{company.name} Product Marketing Manager",
                company_id=company.id,
                company_name=company.name,
                canonical_url=f"https://jobs.ashbyhq.com/{token}/1",
                apply_url=f"https://jobs.ashbyhq.com/{token}/1",
                source_url=f"https://jobs.ashbyhq.com/{token}/1",
                location_display="Remote US",
                location_country="us",
                remote_work_mode="remote",
                employment_type="full_time",
                description_excerpt=f"{company.name} product marketing role.",
                source_status="active",
                is_active=True,
                first_seen_at=now,
                last_seen_at=now,
                source_updated_at=now,
                last_synced_at=now,
            )
            source = JobListingSource(
                job_listing=listing,
                source_provider="ashby",
                provider_type="ats_board",
                provider_job_id=f"{token}:1",
                source_result_id=f"{token}:1",
                ats_provider="ashby",
                ats_board_token=token,
                source_url=listing.source_url,
                apply_url=listing.apply_url,
                canonical_url=listing.canonical_url,
                raw_metadata_json={"provider": "ashby"},
                is_active=True,
                first_seen_at=now,
                last_seen_at=now,
                last_synced_at=now,
            )
            session_arg.add(source)
            session_arg.flush()
            results.append(
                JobSyncResult(
                    request=JobSyncRequest(
                        sync_key=f"ashby:{token}",
                        provider_name="ashby",
                        provider_type="ats_board",
                        sync_kind="company_board",
                        company_id=company.id,
                        company_name=company.name,
                        ats_provider="ashby",
                        ats_board_token=token,
                    ),
                    raw_result_count=1,
                    normalized_count=1,
                    created_count=1,
                )
            )
        return results

    monkeypatch.setattr(candidate_service_module, "sync_greenhouse_boards", fake_sync_greenhouse_boards)
    monkeypatch.setattr(candidate_service_module, "sync_ashby_boards", fake_sync_ashby_boards)
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        profile_id = profile.id
        companies = [
            Company(name="Acme", normalized_name="acme", greenhouse_board_token="acme"),
            Company(name="Beta", normalized_name="beta", ashby_board_url="https://jobs.ashbyhq.com/beta"),
        ]
        session.add_all(companies)
        session.flush()
        session.add_all(
            [
                CandidateCompany(candidate_profile_id=profile.id, company_id=companies[0].id),
                CandidateCompany(candidate_profile_id=profile.id, company_id=companies[1].id),
            ]
        )
        session.commit()

        service = CandidateJobDiscoveryService(
            session=session,
            settings=make_settings(tmp_path),
            planner=FollowedCompanyBoardsPlanner(),
            reviewer=SelectAllReviewer(),
        )
        result = service.run(
            JobDiscoveryRequest(latest_user_message="find jobs from my companies list", candidate_profile_slug=profile.slug),
            candidate_profile=profile,
            current_saved_jobs=[],
            current_saved_companies=[
                {"name": "Acme", "greenhouse_board_token": "acme"},
                {"name": "Beta", "ashby_board_url": "https://jobs.ashbyhq.com/beta"},
            ],
            target_context={},
            private_profile_context={},
        )
        session.commit()

        saved_jobs = list(session.scalars(select(CandidateSavedJob)).all())
        sources = list(session.scalars(select(JobListingSource)).all())

    assert synced_greenhouse_tokens == ["acme"]
    assert synced_ashby_profiles == [profile_id]
    assert result.search_plan.mode == "new_job_discovery"
    assert result.search_plan.use_followed_company_boards is True
    assert result.added_count == 2
    assert result.unique_job_pool_count == 2
    assert {source.source_provider for source in sources} == {"greenhouse", "ashby"}
    assert {source.ats_board_token for source in sources} == {"acme", "beta"}
    assert len(saved_jobs) == 2
    assert all(job.job_listing_id for job in saved_jobs)


def test_jobs_list_ranking_reviews_all_eligible_jobs_and_recommends_top_five(tmp_path) -> None:
    engine = create_candidate_discovery_engine()
    reviewer = RecordingRankingReviewer()
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        for index in range(18):
            job = create_job_listing(session, title=f"Existing Job {index:02d}", provider_job_id=f"rank-{index}")
            session.add(CandidateSavedJob(candidate_profile_id=profile.id, job_listing_id=job.id, status="saved"))
        session.commit()

        service = NoSyncCandidateJobDiscoveryService(
            session=session,
            settings=make_settings(tmp_path),
            planner=StaticJobsListRankingPlanner(limit=300, requested_count=5),
            reviewer=reviewer,
        )
        result = service.run(
            JobDiscoveryRequest(latest_user_message="Which are the first 5 jobs I should apply to?", candidate_profile_slug=profile.slug),
            candidate_profile=profile,
            current_saved_jobs=[],
            current_saved_companies=[],
            target_context={},
            private_profile_context={},
        )
        session.commit()

        links = list(session.scalars(select(CandidateSavedJob)).all())
        rejection_rows = list(session.scalars(select(CandidateJobRejectionReason)).all())
        query_run = session.scalar(select(JobSearchQueryRun).where(JobSearchQueryRun.job_search_run_id == result.job_search_run_id))
        run = session.get(JobSearchRun, result.job_search_run_id)

    assert reviewer.reviewed_counts == [18]
    assert result.recommended_existing_count == 5
    assert result.added_count == 0
    assert result.rejected_count == 0
    assert result.diagnostics["modelReview"]["eligibleJobsListCount"] == 18
    assert result.diagnostics["modelReview"]["requestedRecommendationCount"] == 5
    assert result.diagnostics["modelReview"]["recommendedExistingJobCount"] == 5
    assert result.diagnostics["modelReview"]["recordedModelRejections"] == 0
    assert result.diagnostics["addedJobIds"] == []
    assert len(result.diagnostics["recommendedJobIds"]) == 5
    assert {link.status for link in links} == {"saved"}
    assert all(link.job_search_run_id is None for link in links)
    assert rejection_rows == []
    assert query_run is not None
    assert query_run.raw_result_count == 18
    assert run is not None
    assert run.saved_count == 0
    assert run.model_selected_count == 5


def test_jobs_list_ranking_expands_model_top_five_query_limit(tmp_path) -> None:
    engine = create_candidate_discovery_engine()
    reviewer = RecordingRankingReviewer()
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        for index in range(18):
            job = create_job_listing(session, title=f"Limit Expansion Job {index:02d}", provider_job_id=f"rank-limit-{index}")
            session.add(CandidateSavedJob(candidate_profile_id=profile.id, job_listing_id=job.id, status="saved"))
        session.commit()

        service = NoSyncCandidateJobDiscoveryService(
            session=session,
            settings=make_settings(tmp_path),
            planner=StaticJobsListRankingPlanner(limit=5, requested_count=5),
            reviewer=reviewer,
        )
        result = service.run(
            JobDiscoveryRequest(latest_user_message="Which are the first 5 jobs I should apply to?", candidate_profile_slug=profile.slug),
            candidate_profile=profile,
            current_saved_jobs=[],
            current_saved_companies=[],
            target_context={},
            private_profile_context={},
        )

    assert reviewer.reviewed_counts == [18]
    assert result.search_plan.queries[0].limit >= 18
    assert result.diagnostics["planner"]["inputCapCorrections"][0]["originalLimit"] == 5
    assert result.diagnostics["planner"]["inputCapCorrections"][0]["requestedRecommendationCount"] == 5


def test_jobs_list_ranking_excludes_applied_archived_and_hidden_rows(tmp_path) -> None:
    engine = create_candidate_discovery_engine()
    reviewer = RecordingRankingReviewer()
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        visible = create_job_listing(session, title="Visible Saved", provider_job_id="eligible-visible")
        applied = create_job_listing(session, title="Applied Saved", provider_job_id="eligible-applied")
        archived = create_job_listing(session, title="Archived Saved", provider_job_id="eligible-archived")
        model_rejected = create_job_listing(session, title="Rejected Saved", provider_job_id="eligible-rejected")
        reset = create_job_listing(session, title="Reset Saved", provider_job_id="eligible-reset")
        visible_link = CandidateSavedJob(candidate_profile_id=profile.id, job_listing_id=visible.id, status="saved")
        applied_link = CandidateSavedJob(candidate_profile_id=profile.id, job_listing_id=applied.id, status="saved")
        archived_link = CandidateSavedJob(candidate_profile_id=profile.id, job_listing_id=archived.id, status="saved", archived_at=datetime.now(UTC))
        session.add_all(
            [
                visible_link,
                applied_link,
                archived_link,
                CandidateSavedJob(candidate_profile_id=profile.id, job_listing_id=model_rejected.id, status="model_rejected"),
                CandidateSavedJob(candidate_profile_id=profile.id, job_listing_id=reset.id, status="model_rejection_reset"),
            ]
        )
        session.flush()
        session.add(
            Application(
                candidate_profile_id=profile.id,
                saved_job_id=applied_link.id,
                company_name="Example",
                job_title="Applied Saved",
                status="saved",
            )
        )
        session.commit()

        service = NoSyncCandidateJobDiscoveryService(
            session=session,
            settings=make_settings(tmp_path),
            planner=StaticJobsListRankingPlanner(limit=300, requested_count=5),
            reviewer=reviewer,
        )
        result = service.run(
            JobDiscoveryRequest(latest_user_message="Which job should I apply to first?", candidate_profile_slug=profile.slug),
            candidate_profile=profile,
            current_saved_jobs=[],
            current_saved_companies=[],
            target_context={},
            private_profile_context={},
        )

    assert reviewer.reviewed_titles == [["Visible Saved"]]
    assert result.unique_job_pool_count == 1
    assert result.diagnostics["modelReview"]["eligibleJobsListCount"] == 1


def test_rank_existing_jobs_ignores_model_rejected_jobs_from_response(tmp_path) -> None:
    class RankingConnectorWithRejectedJobs:
        def generate(self, request):
            payload = json.loads(request.messages[-1].content)
            jobs = payload["jobPool"]
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "userVisibleSummary": "I recommend one existing job.",
                        "recommendedJobs": [
                            {
                                "jobListingId": jobs[0]["job_listing_id"],
                                "savedJobId": jobs[0]["saved_job_id"],
                                "rank": 1,
                                "rationale": "Best match.",
                                "matchHighlights": ["Strong fit"],
                                "cautions": [],
                            }
                        ],
                        "rejectedJobs": [{"jobListingId": jobs[1]["job_listing_id"], "reasonCodes": ["role_title"], "explanation": "Not top."}],
                    }
                ),
                finish_reason="stop",
            )

    engine = create_candidate_discovery_engine()
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        for index in range(2):
            job = create_job_listing(session, title=f"Ignore Reject {index}", provider_job_id=f"ignore-reject-{index}")
            session.add(CandidateSavedJob(candidate_profile_id=profile.id, job_listing_id=job.id, status="saved"))
        session.commit()

        service = NoSyncCandidateJobDiscoveryService(
            session=session,
            settings=make_settings(tmp_path),
            connector=RankingConnectorWithRejectedJobs(),
            planner=StaticJobsListRankingPlanner(limit=300, requested_count=1),
        )
        result = service.run(
            JobDiscoveryRequest(latest_user_message="Which job should I apply to first?", candidate_profile_slug=profile.slug),
            candidate_profile=profile,
            current_saved_jobs=[],
            current_saved_companies=[],
            target_context={},
            private_profile_context={},
        )
        session.commit()

        links = list(session.scalars(select(CandidateSavedJob)).all())
        rejection_rows = list(session.scalars(select(CandidateJobRejectionReason)).all())

    assert result.recommended_existing_count == 1
    assert result.rejected_count == 0
    assert result.diagnostics["modelReview"]["ignoredRejectedJobsInRankingMode"] == 1
    assert {link.status for link in links} == {"saved"}
    assert all(link.model_rejected_at is None for link in links)
    assert rejection_rows == []


def test_jobs_list_ranking_batches_all_eligible_jobs(tmp_path) -> None:
    engine = create_candidate_discovery_engine()
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        for index in range(125):
            job = create_job_listing(session, title=f"Batch Ranking {index:03d}", provider_job_id=f"rank-batch-{index}")
            session.add(CandidateSavedJob(candidate_profile_id=profile.id, job_listing_id=job.id, status="saved"))
        session.commit()

        service = NoSyncCandidateJobDiscoveryService(
            session=session,
            settings=replace(make_settings(tmp_path), job_discovery_candidate_pool_limit=50),
            connector=RankingBatchConnector(),
            planner=StaticJobsListRankingPlanner(limit=300, requested_count=5),
        )
        result = service.run(
            JobDiscoveryRequest(latest_user_message="Which are the first 5 jobs I should apply to?", candidate_profile_slug=profile.slug),
            candidate_profile=profile,
            current_saved_jobs=[],
            current_saved_companies=[],
            target_context={},
            private_profile_context={},
        )

    assert result.diagnostics["modelReview"]["eligibleJobsListCount"] == 125
    assert result.diagnostics["modelReview"]["reviewBatchCount"] == 3
    assert result.diagnostics["modelReview"]["perBatchReviewedCount"] == [50, 50, 25]
    assert result.diagnostics["modelReview"]["jobsReviewedByModel"] == 125
    assert result.recommended_existing_count == 5
    assert result.rejected_count == 0


def test_filtered_apply_prioritization_corrects_mixed_plan_to_jobs_list_ranking(tmp_path, monkeypatch) -> None:
    def fail_sync(*args, **kwargs):
        raise AssertionError("jobs-list ranking must not run sync")

    monkeypatch.setattr(candidate_service_module, "sync_greenhouse_boards", fail_sync)
    monkeypatch.setattr(candidate_service_module, "sync_ashby_boards", fail_sync)
    monkeypatch.setattr(candidate_service_module, "sync_adzuna_signatures", fail_sync)
    engine = create_candidate_discovery_engine()
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        saved = create_job_listing(session, title="US Remote Saved AI Job", provider_job_id="filtered-saved")
        other = create_job_listing(session, title="UK Remote Saved AI Job", provider_job_id="filtered-other")
        other.location_country = "gb"
        session.add_all(
            [
                CandidateSavedJob(candidate_profile_id=profile.id, job_listing_id=saved.id, status="saved"),
                CandidateSavedJob(candidate_profile_id=profile.id, job_listing_id=other.id, status="saved"),
            ]
        )
        session.commit()

        service = CandidateJobDiscoveryService(
            session=session,
            settings=make_settings(tmp_path),
            connector=MixedPlanCorrectedToRankingConnector(),
        )
        result = service.run(
            JobDiscoveryRequest(latest_user_message="what US remote jobs should I apply to today?", candidate_profile_slug=profile.slug),
            candidate_profile=profile,
            current_saved_jobs=[],
            current_saved_companies=[],
            target_context={},
            private_profile_context={},
        )
        session.commit()

        links = list(session.scalars(select(CandidateSavedJob)).all())

    assert result.search_plan.mode == "jobs_list_review"
    assert result.search_plan.review_plan.task == "rank_existing_jobs"
    assert result.search_plan.use_followed_company_boards is False
    assert result.search_plan.proposed_adzuna_signatures == ()
    assert result.job_sync_results == ()
    assert result.added_count == 0
    assert result.recommended_existing_count == 1
    assert result.diagnostics["planner"]["rejectedPlans"][0]["issueCode"] == "mode_mismatch_apply_prioritization"
    assert result.diagnostics["addedJobIds"] == []
    assert len(result.diagnostics["recommendedJobIds"]) == 1
    assert all(link.job_search_run_id is None for link in links)


def test_rank_existing_jobs_executor_guard_ignores_unsaved_recommendations(tmp_path, monkeypatch) -> None:
    def fail_sync(*args, **kwargs):
        raise AssertionError("rank_existing_jobs must not run sync")

    monkeypatch.setattr(candidate_service_module, "sync_greenhouse_boards", fail_sync)
    monkeypatch.setattr(candidate_service_module, "sync_ashby_boards", fail_sync)
    monkeypatch.setattr(candidate_service_module, "sync_adzuna_signatures", fail_sync)
    engine = create_candidate_discovery_engine()
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        saved = create_job_listing(session, title="Saved US Remote", provider_job_id="guard-saved")
        unsaved = create_job_listing(session, title="Unsaved US Remote", provider_job_id="guard-unsaved")
        saved_listing_id = saved.id
        unsaved_listing_id = unsaved.id
        session.add(CandidateSavedJob(candidate_profile_id=profile.id, job_listing_id=saved.id, status="saved"))
        session.commit()

        service = CandidateJobDiscoveryService(
            session=session,
            settings=make_settings(tmp_path),
            planner=UnsafeMixedRankingPlanner(unsaved_job_listing_id=unsaved_listing_id),
            reviewer=StaticRecommendationReviewer(job_listing_ids=[unsaved_listing_id]),
        )
        result = service.run(
            JobDiscoveryRequest(latest_user_message="Find new jobs and rank them with my saved jobs.", candidate_profile_slug=profile.slug),
            candidate_profile=profile,
            current_saved_jobs=[],
            current_saved_companies=[],
            target_context={},
            private_profile_context={},
        )
        session.commit()

        links = list(session.scalars(select(CandidateSavedJob)).all())

    assert result.search_plan.mode == "jobs_list_review"
    assert result.search_plan.job_scope == "candidate_jobs_list"
    assert result.job_sync_results == ()
    assert result.added_count == 0
    assert result.recommended_existing_count == 0
    assert len(links) == 1
    assert links[0].job_listing_id == saved_listing_id
    assert result.diagnostics["addedJobIds"] == []
    assert result.diagnostics["recommendedJobIds"] == []
    assert result.diagnostics["modelReview"]["ignoredNonListRecommendations"] == 1
    assert unsaved_listing_id in result.diagnostics["modelReview"]["ignoredNonListRecommendationJobListingIds"]


def test_jobs_list_ranking_filter_applies_to_saved_list_entries(tmp_path) -> None:
    engine = create_candidate_discovery_engine()
    reviewer = RecordingRankingReviewer()
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        us_remote = create_job_listing(session, title="US Remote Saved", provider_job_id="saved-us-remote")
        us_hybrid = create_job_listing(session, title="US Hybrid Saved", provider_job_id="saved-us-hybrid")
        us_hybrid.remote_work_mode = "hybrid"
        uk_remote = create_job_listing(session, title="UK Remote Saved", provider_job_id="saved-uk-remote")
        uk_remote.location_country = "gb"
        session.add_all(
            [
                CandidateSavedJob(candidate_profile_id=profile.id, job_listing_id=us_remote.id, status="saved"),
                CandidateSavedJob(candidate_profile_id=profile.id, job_listing_id=us_hybrid.id, status="saved"),
                CandidateSavedJob(candidate_profile_id=profile.id, job_listing_id=uk_remote.id, status="saved"),
            ]
        )
        session.commit()

        service = NoSyncCandidateJobDiscoveryService(
            session=session,
            settings=make_settings(tmp_path),
            planner=FilteredJobsListRankingPlanner(location_countries=("us",), remote_modes=("remote",), requested_count=5),
            reviewer=reviewer,
        )
        result = service.run(
            JobDiscoveryRequest(latest_user_message="what US remote jobs should I apply to today?", candidate_profile_slug=profile.slug),
            candidate_profile=profile,
            current_saved_jobs=[],
            current_saved_companies=[],
            target_context={},
            private_profile_context={},
        )

    assert reviewer.reviewed_titles == [["US Remote Saved"]]
    assert result.unique_job_pool_count == 1
    assert result.added_count == 0
    assert result.diagnostics["modelReview"]["eligibleJobsListCount"] == 1


def test_jobs_list_ranking_fewer_than_requested_asks_before_searching(tmp_path) -> None:
    engine = create_candidate_discovery_engine()
    reviewer = RecordingRankingReviewer()
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        for index in range(3):
            job = create_job_listing(session, title=f"Available Saved {index}", provider_job_id=f"available-{index}")
            session.add(CandidateSavedJob(candidate_profile_id=profile.id, job_listing_id=job.id, status="saved"))
        session.commit()

        service = NoSyncCandidateJobDiscoveryService(
            session=session,
            settings=make_settings(tmp_path),
            planner=StaticJobsListRankingPlanner(limit=300, requested_count=5),
            reviewer=reviewer,
        )
        result = service.run(
            JobDiscoveryRequest(latest_user_message="Which are the first 5 jobs I should apply to?", candidate_profile_slug=profile.slug),
            candidate_profile=profile,
            current_saved_jobs=[],
            current_saved_companies=[],
            target_context={},
            private_profile_context={},
        )

    assert result.recommended_existing_count == 3
    assert result.added_count == 0
    assert result.diagnostics["modelReview"]["fewerThanRequestedRecommendations"] is True
    assert result.diagnostics["modelReview"]["availableMatchingSavedListJobs"] == 3
    assert "search for new jobs" in result.assistant_message


def test_planner_payload_includes_existing_sync_context_without_secrets(tmp_path) -> None:
    engine = create_candidate_discovery_engine()
    with Session(engine) as session:
        create_candidate_profile(session)
        session.add(
            JobSyncSignature(
                sync_key="adzuna:broad:gb:remote-uk:ai",
                provider_name="adzuna",
                provider_type="broad_search",
                sync_kind="broad_search",
                query_text="AI",
                query_kind="broad_term",
                display_location="Remote UK",
                provider_country="gb",
                provider_where=None,
                enabled=True,
                verification_status="verified",
                last_raw_result_count=50,
                last_normalized_count=49,
                criteria_json={"app_id": "secret", "app_key": "secret"},
            )
        )
        service = CandidateJobDiscoveryService(session=session, settings=make_settings(tmp_path))
        context = service.build_planner_inventory_context()
        request = DbJobSearchPlanner().build_model_request(
            JobDiscoveryRequest(latest_user_message="Find AI jobs.", candidate_profile_slug="rebekah-love"),
            current_saved_jobs=[],
            current_saved_companies=[],
            target_context={},
            private_profile_context={},
            inventory_context=context,
        )

    payload = json.loads(request.messages[-1].content)

    signature = payload["inventoryContext"]["existingAdzunaSignatures"][0]
    assert signature["syncKey"] == "adzuna:broad:gb:remote-uk:ai"
    assert "syncedInventorySummary" in payload["inventoryContext"]
    assert "app_id" not in request.messages[-1].content
    assert "app_key" not in request.messages[-1].content


def test_planner_payload_includes_recent_db_query_history(tmp_path) -> None:
    engine = create_candidate_discovery_engine()
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        run = JobSearchRun(
            candidate_profile_id=profile.id,
            command_text="Find jobs.",
            search_plan_json={},
            run_diagnostics_json={"noJobsAddedReason": "no_db_matches"},
            provider_names=[],
            search_mode="db_backed",
            status="completed",
        )
        session.add(run)
        session.flush()
        session.add(
            JobSearchQueryRun(
                job_search_run_id=run.id,
                provider_name="database",
                query="Previous zero result search",
                total_matches=0,
                raw_result_count=0,
                normalized_result_count=0,
                deduped_result_count=0,
                candidate_count_after_filters=0,
            )
        )
        session.commit()

        service = CandidateJobDiscoveryService(session=session, settings=make_settings(tmp_path))
        context = service.build_planner_inventory_context(current_saved_jobs=[])

    assert context["recentDbQueryRuns"][0]["label"] == "Previous zero result search"
    assert context["recentDbQueryRuns"][0]["resultCount"] == 0
    assert context["recentDbQueryRuns"][0]["noJobsAddedReason"] == "no_db_matches"


def test_validation_ignores_unknown_model_ids_and_creates_no_rows(tmp_path) -> None:
    engine = create_candidate_discovery_engine()
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        create_job_listing(session, title="AI Engineer", provider_job_id="known")
        session.commit()

        service = NoSyncCandidateJobDiscoveryService(
            session=session,
            settings=make_settings(tmp_path),
            planner=StaticPlanner(),
            reviewer=UnknownIdReviewer(),
        )
        result = service.run(
            JobDiscoveryRequest(latest_user_message="Find jobs.", candidate_profile_slug=profile.slug),
            candidate_profile=profile,
            current_saved_jobs=[],
            current_saved_companies=[],
            target_context={},
            private_profile_context={},
        )
        session.commit()

        rows = list(session.scalars(select(CandidateSavedJob)).all())

    assert rows == []
    assert result.diagnostics["modelReview"]["reviewValidation"]["invalidSelectedJobIds"] == ["missing-selected"]
    assert result.diagnostics["modelReview"]["reviewValidation"]["invalidRejectedJobIds"] == ["missing-rejected"]


def test_db_backed_result_zero_pool_exposes_no_db_matches() -> None:
    discovery = make_candidate_discovery_result(
        diagnostics={
            "jobSync": {"runs": [], "completedCount": 0, "failedCount": 0},
            "databaseQueries": {"queries": [], "uniqueJobPoolCount": 0, "totalRowsMatched": 0},
            "modelReview": {
                "uniqueJobsInPool": 0,
                "jobsReviewedByModel": 0,
                "addedToCandidateJobsList": 0,
                "recordedModelRejections": 0,
            },
            "noJobsAddedReason": "no_db_matches",
        },
        unique_job_pool_count=0,
        jobs_reviewed_count=0,
        added_count=0,
    )

    payload = build_db_backed_job_discovery_result(
        discovery,
        current_saved_jobs=[],
        current_saved_companies=[],
    ).body["result"]

    assert payload["noJobsAddedReason"] == "no_db_matches"
    assert payload["databaseMatchedJobCount"] == 0


def test_db_backed_result_model_failure_exposes_failure_reason() -> None:
    discovery = make_candidate_discovery_result(
        diagnostics={
            "jobSync": {"runs": [], "completedCount": 0, "failedCount": 0},
            "databaseQueries": {"queries": [{"label": "Synced search", "jobCount": 1}], "uniqueJobPoolCount": 1},
            "modelReview": {
                "uniqueJobsInPool": 1,
                "jobsReviewedByModel": 0,
                "addedToCandidateJobsList": 0,
                "recordedModelRejections": 0,
                "modelReviewCompleted": False,
                "modelReviewFallback": True,
                "modelReviewFailureReason": "model unavailable",
            },
            "noJobsAddedReason": "model_review_failed",
        },
        unique_job_pool_count=1,
        jobs_reviewed_count=0,
        added_count=0,
    )

    payload = build_db_backed_job_discovery_result(
        discovery,
        current_saved_jobs=[],
        current_saved_companies=[],
    ).body["result"]

    assert payload["noJobsAddedReason"] == "model_review_failed"
    assert payload["modelReviewCompleted"] is False
    assert payload["modelReviewFailureReason"] == "model unavailable"


def test_db_backed_result_empty_completed_review_exposes_selected_zero() -> None:
    discovery = make_candidate_discovery_result(
        diagnostics={
            "jobSync": {"runs": [], "completedCount": 0, "failedCount": 0},
            "databaseQueries": {"queries": [{"label": "Synced search", "jobCount": 1}], "uniqueJobPoolCount": 1},
            "modelReview": {
                "uniqueJobsInPool": 1,
                "jobsReviewedByModel": 1,
                "addedToCandidateJobsList": 0,
                "recordedModelRejections": 0,
                "modelReviewCompleted": True,
            },
            "noJobsAddedReason": "model_selected_zero",
        },
        unique_job_pool_count=1,
        jobs_reviewed_count=1,
        added_count=0,
    )

    payload = build_db_backed_job_discovery_result(
        discovery,
        current_saved_jobs=[],
        current_saved_companies=[],
    ).body["result"]

    assert payload["noJobsAddedReason"] == "model_selected_zero"
    assert payload["jobsReviewedByModel"] == 1


def test_status_serialization_includes_db_backed_diagnostics_and_added_jobs(tmp_path) -> None:
    engine = create_candidate_discovery_engine()
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        job = create_job_listing(session, title="AI Product Engineer", provider_job_id="status-added")
        run = JobSearchRun(
            candidate_profile_id=profile.id,
            command_text="Find AI jobs.",
            search_mode="db_backed",
            status="completed",
            provider_names=["job_sync", "database", "model_review"],
            candidate_pool_count=1,
            candidate_count_after_dedupe=1,
            model_selected_count=1,
            saved_count=1,
            skipped_count=0,
            run_diagnostics_json={
                "jobSync": {"runs": [{"syncKey": "adzuna:test", "status": "completed", "raw": 1, "normalized": 1, "created": 1, "updated": 0}]},
                "databaseQueries": {"queries": [{"label": "Synced search", "jobCount": 1}], "uniqueJobPoolCount": 1},
                "modelReview": {
                    "uniqueJobsInPool": 1,
                    "jobsReviewedByModel": 1,
                    "addedToCandidateJobsList": 1,
                    "recordedModelRejections": 0,
                    "modelReviewCompleted": True,
                },
            },
        )
        session.add(run)
        session.flush()
        link = CandidateSavedJob(candidate_profile_id=profile.id, job_listing_id=job.id, job_search_run_id=run.id, status="new")
        session.add(link)
        session.commit()

        payload = serialize_job_search_run_status(run, [], session=session, candidate_profile_id=profile.id)

    assert payload["jobDiscoveryMode"] == "db_backed"
    assert payload["diagnostics"]["jobSync"]["runs"][0]["syncKey"] == "adzuna:test"
    assert payload["diagnostics"]["databaseQueries"]["uniqueJobPoolCount"] == 1
    assert payload["addedJobIds"] == [link.id]
    assert payload["addedJobs"][0]["job_listing_id"] == job.id
    assert payload["highlightedJobSearchRunId"] == run.id


def test_validate_review_result_selected_wins_and_dedupes_rejections() -> None:
    review = JobReviewResult(
        user_visible_summary="Reviewed.",
        selected_jobs=(
            SelectedJobDecision(job_listing_id="job-1", rationale="first"),
            SelectedJobDecision(job_listing_id="job-1", rationale="duplicate"),
        ),
        rejected_jobs=(
            RejectedJobDecision(job_listing_id="job-1", reason_codes=("location",)),
            RejectedJobDecision(job_listing_id="job-2", reason_codes=("location",)),
            RejectedJobDecision(job_listing_id="job-2", reason_codes=("role_title",)),
            RejectedJobDecision(job_listing_id="missing", reason_codes=("other",)),
        ),
    )

    validated = validate_review_result(review, ("job-1", "job-2"))

    assert [decision.job_listing_id for decision in validated.selected_jobs] == ["job-1"]
    assert [decision.job_listing_id for decision in validated.rejected_jobs] == ["job-2"]
    assert validated.rejected_jobs[0].reason_codes == ("location", "role_title")
    assert validated.diagnostics["reviewValidation"]["duplicateDecisionCount"] == 2
    assert validated.diagnostics["reviewValidation"]["selectedWinsConflictCount"] == 1
    assert validated.diagnostics["reviewValidation"]["invalidRejectedJobIds"] == ["missing"]


class UnknownIdReviewer:
    def review(self, *args, **kwargs) -> JobReviewResult:
        return JobReviewResult(
            user_visible_summary="Model returned unknown ids.",
            selected_jobs=(SelectedJobDecision(job_listing_id="missing-selected"),),
            rejected_jobs=(RejectedJobDecision(job_listing_id="missing-rejected", reason_codes=("other",)),),
            diagnostics={"modelReviewCompleted": True},
        )


def test_theirstack_consideration_is_visible_for_fresh_job_discovery(tmp_path) -> None:
    settings = replace(
        make_settings(tmp_path),
        theirstack_api_key="their-stack-test-key",
        theirstack_company_search_enabled=True,
    )
    plan = DbJobSearchPlan(mode="new_job_discovery", job_scope="new_to_candidate")
    row = build_theirstack_provider_consideration(
        settings,
        request=JobDiscoveryRequest(latest_user_message="Find fresh companies hiring AI engineers.", candidate_profile_slug="rebekah-love"),
        plan=plan,
        called=False,
    )
    diagnostics = {
        "planner": {"providerConsiderations": [row]},
        "jobSync": {"runs": []},
        "databaseQueries": {"queries": []},
        "modelReview": {},
    }

    assert row["available"] is True
    assert row["consideredForFreshDiscovery"] is True
    assert row["selectedForFreshDiscovery"] is True
    assert row["called"] is False
    assert row["skippedReason"] == "theirstack_is_company_hiring_signal_source_not_canonical_job_detail_source"
    assert "Provider theirstack - skipped" in format_candidate_discovery_diagnostics(diagnostics)


def test_provider_failure_error_is_in_discovery_diagnostics() -> None:
    diagnostics = build_candidate_discovery_diagnostics(
        job_sync_results=(
            JobSyncResult(
                request=JobSyncRequest(sync_key="adzuna:test", provider_name="adzuna", provider_type="broad_search", sync_kind="broad_search"),
                status="failed",
                error="provider unavailable",
            ),
        ),
        query_counts=(),
        unique_job_pool_count=0,
        jobs_reviewed_count=0,
        added_count=0,
        rejected_count=0,
        rejection_reason_counts={},
    )

    assert diagnostics["jobSync"]["failedCount"] == 1
    assert diagnostics["jobSync"]["runs"][0]["error"] == "provider unavailable"
    assert "error=provider unavailable" in format_candidate_discovery_diagnostics(diagnostics)


class ProposedAdzunaPlanner:
    def plan(self, *args, **kwargs) -> DbJobSearchPlan:
        return DbJobSearchPlan(
            job_scope="new_to_candidate",
            proposed_adzuna_signatures=(
                {
                    "queryText": "AI",
                    "displayLocation": "Remote US",
                    "queryKind": "model_planned",
                    "maxPages": 1,
                },
            ),
            queries=(
                DbJobSearchQuery(
                    label="Model-planned AI search",
                    title_terms_any=("AI",),
                    source_providers_any=("adzuna",),
                    limit=100,
                ),
            ),
            max_jobs_for_model_review=10,
        )


class SelectFirstReviewer:
    def review(self, *args, job_pool, **kwargs) -> JobReviewResult:
        return JobReviewResult(
            user_visible_summary="I found one strong synced job.",
            selected_jobs=(SelectedJobDecision(job_listing_id=job_pool[0].job_listing_id, rationale="Strong match."),),
            diagnostics={"modelReviewCompleted": True},
        )


def test_model_only_job_listing_without_fresh_provider_source_is_not_saved(tmp_path) -> None:
    engine = create_candidate_discovery_engine()
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        stale_model_only = JobListing(
            title="Model Memory AI Engineer",
            company_name="Unverified Co",
            canonical_url="https://example.test/model-memory",
            apply_url="https://example.test/model-memory/apply",
            source_url="https://example.test/model-memory",
            location_display="Remote US",
            location_country="us",
            remote_work_mode="remote",
            employment_type="full_time",
            description_excerpt="This row has no provider source.",
            source_status="active",
            is_active=True,
            last_seen_at=datetime.now(UTC),
            source_updated_at=datetime.now(UTC),
        )
        session.add(stale_model_only)
        fresh_provider_job = create_job_listing(session, title="Fresh Provider AI Engineer", provider="adzuna", provider_job_id="fresh-provider")
        fresh_provider_job_id = fresh_provider_job.id
        fresh_provider_job_source_url = fresh_provider_job.source_url
        session.commit()

        service = NoSyncCandidateJobDiscoveryService(
            session=session,
            settings=make_settings(tmp_path),
            planner=StaticPlanner(),
            reviewer=SelectFirstReviewer(),
        )
        result = service.run(
            JobDiscoveryRequest(latest_user_message="Find fresh AI jobs.", candidate_profile_slug=profile.slug),
            candidate_profile=profile,
            current_saved_jobs=[],
            current_saved_companies=[],
            target_context={},
            private_profile_context={},
        )
        session.commit()
        saved = list(session.scalars(select(CandidateSavedJob)).all())
        saved_listing_ids = [link.job_listing_id for link in saved]
        saved_metadata = [dict(link.discovery_metadata or {}) for link in saved]

    assert result.unique_job_pool_count == 1
    assert saved_listing_ids == [fresh_provider_job_id]
    assert saved_metadata[0]["sourceProvider"] == "adzuna"
    assert saved_metadata[0]["sourceUrl"] == fresh_provider_job_source_url
    assert saved_metadata[0]["fetchedAt"]


class CriticCorrectsConnector:
    def generate(self, request):
        if request.task == "candidate_db_job_search_planning":
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "mode": "jobs_list_review",
                        "modeRationale": "Incorrectly reviewing an empty jobs list.",
                        "syncPlan": {
                            "useFollowedCompanyBoards": False,
                            "proposedAdzunaSignatures": [],
                            "existingAdzunaSignatureIdsToRefresh": [],
                            "rationale": "No sync planned.",
                        },
                        "dbSearchPlan": {
                            "queries": [
                                {
                                    "label": "Review visible jobs list",
                                    "activeOnly": True,
                                    "includeModelRejected": False,
                                    "limit": 100,
                                    "orderBy": "last_seen_at_desc",
                                }
                            ]
                        },
                    }
                )
            )
        if request.task == "candidate_db_job_plan_critique":
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "valid": False,
                        "issueCode": "mode_mismatch",
                        "issueMessage": "The user asked to find new jobs, but the plan reviews an empty jobs list.",
                        "correctedPlan": {
                            "mode": "new_job_discovery",
                            "modeRationale": "The user asked to find jobs to apply to.",
                            "syncPlan": {
                                "useFollowedCompanyBoards": False,
                                "proposedAdzunaSignatures": [
                                    {
                                        "queryText": "AI",
                                        "displayLocation": "Remote US",
                                        "queryKind": "model_planned",
                                        "maxPages": 1,
                                    }
                                ],
                                "existingAdzunaSignatureIdsToRefresh": [],
                                "rationale": "Use a broad sync token before database search.",
                            },
                            "dbSearchPlan": {
                                "queries": [
                                    {
                                        "label": "AI synced jobs",
                                        "activeOnly": True,
                                        "sourceProvidersAny": ["adzuna"],
                                        "titleTermsAny": ["AI"],
                                        "includeModelRejected": False,
                                        "limit": 100,
                                        "orderBy": "last_seen_at_desc",
                                    }
                                ]
                            },
                            "replanRules": {
                                "minJobPoolSize": 1,
                                "maxJobPoolSize": 100,
                                "maxJobsForModelReview": 10,
                            },
                        },
                    }
                )
            )
        raise AssertionError(f"Unexpected task {request.task}")


class JobsListReviewConnector:
    def generate(self, request):
        if request.task == "candidate_db_job_search_planning":
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "mode": "jobs_list_review",
                        "modeRationale": "The user asked which existing jobs to apply to first.",
                        "syncPlan": {
                            "useFollowedCompanyBoards": False,
                            "proposedAdzunaSignatures": [],
                            "existingAdzunaSignatureIdsToRefresh": [],
                            "rationale": "No new inventory needed for a jobs-list review.",
                        },
                        "dbSearchPlan": {
                            "queries": [
                                {
                                    "label": "Review visible jobs list",
                                    "activeOnly": True,
                                    "includeModelRejected": False,
                                    "limit": 100,
                                    "orderBy": "last_seen_at_desc",
                                }
                            ]
                        },
                        "replanRules": {
                            "minJobPoolSize": 1,
                            "maxJobPoolSize": 100,
                            "maxJobsForModelReview": 10,
                        },
                    }
                )
            )
        if request.task == "candidate_db_job_plan_critique":
            return SimpleNamespace(text=json.dumps({"valid": True, "issueCode": None, "issueMessage": None, "correctedPlan": None}))
        raise AssertionError(f"Unexpected task {request.task}")


class FollowedCompanyBoardsPlanner:
    def plan(self, *args, **kwargs) -> DbJobSearchPlan:
        return DbJobSearchPlan(
            mode="new_job_discovery",
            job_scope="new_to_candidate",
            mode_rationale="The user asked to find new jobs from saved companies.",
            use_followed_company_boards=True,
            sync_plan_rationale="Sync followed company first-party ATS boards.",
            queries=(
                DbJobSearchQuery(
                    label="Search first-party ATS jobs from followed companies",
                    source_providers_any=("greenhouse", "ashby"),
                    source_statuses_any=("active",),
                    limit=300,
                ),
            ),
            min_job_pool_size=1,
            max_job_pool_size=300,
            max_jobs_for_model_review=80,
            review_plan=ReviewPlan(
                task="select_new_jobs",
                requested_count=5,
                allow_rejections=True,
                review_all_eligible_jobs=False,
                rationale="Select matching jobs from synced company boards.",
            ),
        )


class SelectAllReviewer:
    def review(self, *args, job_pool, **kwargs) -> JobReviewResult:
        return JobReviewResult(
            user_visible_summary=f"I selected {len(job_pool)} synced jobs from your companies list.",
            selected_jobs=tuple(
                SelectedJobDecision(job_listing_id=entry.job_listing_id, rationale="Matches followed-company search.")
                for entry in job_pool
            ),
            diagnostics={"modelReviewCompleted": True},
        )


class StaticJobsListRankingPlanner:
    def __init__(self, *, limit: int, requested_count: int) -> None:
        self.limit = limit
        self.requested_count = requested_count

    def plan(self, *args, **kwargs) -> DbJobSearchPlan:
        return DbJobSearchPlan(
            mode="jobs_list_review",
            job_scope="candidate_jobs_list",
            mode_rationale="The user asked which existing jobs to apply to first.",
            queries=(
                DbJobSearchQuery(
                    label="Review active unapplied jobs from the jobs list",
                    source_statuses_any=("active",),
                    limit=self.limit,
                    order_by="last_seen_at_desc",
                ),
            ),
            min_job_pool_size=1,
            max_job_pool_size=300,
            max_jobs_for_model_review=80,
            review_plan=ReviewPlan(
                task="rank_existing_jobs",
                requested_count=self.requested_count,
                allow_rejections=False,
                review_all_eligible_jobs=True,
                rationale="Rank all active, unarchived, unapplied jobs from the jobs list.",
            ),
        )


class FilteredJobsListRankingPlanner:
    def __init__(
        self,
        *,
        location_countries: tuple[str, ...] = (),
        remote_modes: tuple[str, ...] = (),
        requested_count: int,
    ) -> None:
        self.location_countries = location_countries
        self.remote_modes = remote_modes
        self.requested_count = requested_count

    def plan(self, *args, **kwargs) -> DbJobSearchPlan:
        return DbJobSearchPlan(
            mode="jobs_list_review",
            job_scope="candidate_jobs_list",
            mode_rationale="The user asked which filtered saved jobs to apply to first.",
            queries=(
                DbJobSearchQuery(
                    label="Review active unapplied filtered jobs from the jobs list",
                    source_statuses_any=("active",),
                    location_countries_any=self.location_countries,
                    remote_work_modes_any=self.remote_modes,
                    limit=300,
                ),
            ),
            min_job_pool_size=1,
            max_job_pool_size=300,
            review_plan=ReviewPlan(
                task="rank_existing_jobs",
                requested_count=self.requested_count,
                allow_rejections=False,
                review_all_eligible_jobs=True,
            ),
        )


class UnsafeMixedRankingPlanner:
    def __init__(self, *, unsaved_job_listing_id: str) -> None:
        self.unsaved_job_listing_id = unsaved_job_listing_id

    def plan(self, *args, **kwargs) -> DbJobSearchPlan:
        return DbJobSearchPlan(
            mode="mixed_new_and_existing",
            job_scope="all_accessible_jobs",
            mode_rationale="Unsafe one-pass mixed ranking plan.",
            use_followed_company_boards=True,
            proposed_adzuna_signatures=({"queryText": "AI", "displayLocation": "Remote US", "queryKind": "model_planned"},),
            queries=(DbJobSearchQuery(label="Unsafe all accessible ranking", source_statuses_any=("active",), limit=300),),
            min_job_pool_size=1,
            max_job_pool_size=300,
            review_plan=ReviewPlan(
                task="rank_existing_jobs",
                requested_count=5,
                allow_rejections=False,
                review_all_eligible_jobs=True,
            ),
        )


class StaticRecommendationReviewer:
    def __init__(self, *, job_listing_ids: list[str]) -> None:
        self.job_listing_ids = job_listing_ids

    def review(self, *args, **kwargs) -> JobReviewResult:
        return JobReviewResult(
            user_visible_summary="I recommend these existing jobs.",
            selected_jobs=tuple(SelectedJobDecision(job_listing_id=job_listing_id) for job_listing_id in self.job_listing_ids),
            diagnostics={"modelReviewCompleted": True, "reviewMode": "rank_existing_jobs"},
        )


class MixedPlanCorrectedToRankingConnector:
    def generate(self, request):
        if request.task == "candidate_db_job_search_planning":
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "mode": "mixed_new_and_existing",
                        "modeRationale": "Incorrectly treated filters as new discovery.",
                        "syncPlan": {
                            "useFollowedCompanyBoards": True,
                            "proposedAdzunaSignatures": [
                                {
                                    "queryText": "AI",
                                    "displayLocation": "Remote US",
                                    "queryKind": "model_planned",
                                    "maxPages": 1,
                                }
                            ],
                            "existingAdzunaSignatureIdsToRefresh": [],
                            "rationale": "Incorrect sync.",
                        },
                        "dbSearchPlan": {
                            "queries": [
                                {
                                    "label": "Unsafe mixed US remote search",
                                    "activeOnly": True,
                                    "locationCountriesAny": ["us"],
                                    "remoteWorkModesAny": ["remote"],
                                    "limit": 300,
                                    "orderBy": "last_seen_at_desc",
                                }
                            ]
                        },
                        "reviewPlan": {
                            "task": "rank_existing_jobs",
                            "requestedCount": 5,
                            "allowRejections": False,
                            "reviewAllEligibleJobs": True,
                        },
                    }
                )
            )
        if request.task == "candidate_db_job_plan_critique":
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "valid": False,
                        "issueCode": "mode_mismatch_apply_prioritization",
                        "issueMessage": "The user asked which jobs to apply to, with filters.",
                        "correctedPlan": {
                            "mode": "jobs_list_review",
                            "modeRationale": "The user asked which US remote jobs on the jobs list to apply to today.",
                            "syncPlan": {
                                "useFollowedCompanyBoards": False,
                                "proposedAdzunaSignatures": [],
                                "existingAdzunaSignatureIdsToRefresh": [],
                                "rationale": "No new inventory needed.",
                            },
                            "dbSearchPlan": {
                                "queries": [
                                    {
                                        "label": "Review active unapplied US remote jobs from the jobs list",
                                        "activeOnly": True,
                                        "locationCountriesAny": ["us"],
                                        "remoteWorkModesAny": ["remote"],
                                        "includeModelRejected": False,
                                        "limit": 300,
                                        "orderBy": "last_seen_at_desc",
                                    }
                                ]
                            },
                            "reviewPlan": {
                                "task": "rank_existing_jobs",
                                "requestedCount": 5,
                                "allowRejections": False,
                                "reviewAllEligibleJobs": True,
                                "rationale": "Rank matching existing jobs-list entries.",
                            },
                            "replanRules": {
                                "minJobPoolSize": 1,
                                "maxJobPoolSize": 300,
                                "maxJobsForModelReview": 80,
                            },
                        },
                    }
                )
            )
        if request.task == "candidate_job_review":
            payload = json.loads(request.messages[-1].content)
            jobs = payload["jobPool"]
            selected = [
                {
                    "jobListingId": job["job_listing_id"],
                    "savedJobId": job["saved_job_id"],
                    "rank": index + 1,
                    "rationale": "Matches the US remote filter.",
                    "matchHighlights": ["US remote"],
                    "cautions": [],
                }
                for index, job in enumerate(jobs[:5])
            ]
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "userVisibleSummary": f"I reviewed {len(jobs)} US remote saved-list jobs.",
                        "recommendedJobs": selected,
                    }
                ),
                finish_reason="stop",
            )
        raise AssertionError(f"Unexpected task {request.task}")


class RecordingRankingReviewer:
    def __init__(self) -> None:
        self.reviewed_counts: list[int] = []
        self.reviewed_titles: list[list[str]] = []

    def review(self, *args, job_pool, requested_count=None, **kwargs) -> JobReviewResult:
        self.reviewed_counts.append(len(job_pool))
        self.reviewed_titles.append([entry.title for entry in job_pool])
        selected = tuple(
            SelectedJobDecision(
                job_listing_id=entry.job_listing_id,
                saved_job_id=entry.saved_job_id,
                rank=index + 1,
                rationale="Recommended existing job.",
            )
            for index, entry in enumerate(job_pool[: requested_count or 5])
        )
        rejected = (RejectedJobDecision(job_listing_id=job_pool[-1].job_listing_id, reason_codes=("other",)),) if job_pool else ()
        return JobReviewResult(
            user_visible_summary=f"I reviewed {len(job_pool)} jobs from your list.",
            selected_jobs=selected,
            rejected_jobs=rejected,
            diagnostics={
                "modelReviewCompleted": True,
                "reviewMode": "rank_existing_jobs",
                "eligibleJobsListCount": len(job_pool),
                "jobsReviewedByModel": len(job_pool),
                "requestedRecommendationCount": requested_count or 5,
                "finalRecommendedCount": len(selected),
                "reviewBatchCount": 1,
                "perBatchReviewedCount": [len(job_pool)],
                "perBatchShortlistCount": [len(selected)],
            },
        )


class RankingBatchConnector:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def generate(self, request):
        payload = json.loads(request.messages[-1].content)
        self.calls.append(payload)
        jobs = payload["jobPool"]
        requested_count = int(payload["requestedCount"])
        selected = [
            {
                "jobListingId": job["job_listing_id"],
                "savedJobId": job["saved_job_id"],
                "rank": index + 1,
                "rationale": "Recommended existing job.",
                "matchHighlights": [],
                "cautions": [],
            }
            for index, job in enumerate(jobs[:requested_count])
        ]
        return SimpleNamespace(
            text=json.dumps(
                {
                    "userVisibleSummary": f"I recommend {len(selected)} existing jobs.",
                    "recommendedJobs": selected,
                    "notSelectedSummary": "Other jobs remain unchanged.",
                }
            ),
            finish_reason="stop",
        )


def make_candidate_discovery_result(**overrides):
    defaults = {
        "assistant_message": "Reviewed synced jobs.",
        "job_search_run_id": "run-test",
        "search_plan": DbJobSearchPlan(
            job_scope="new_to_candidate",
            queries=(DbJobSearchQuery(source_statuses_any=("active",), limit=10),),
            max_jobs_for_model_review=10,
        ),
        "selected_candidate_jobs": (),
        "updated_candidate_jobs": (),
        "rejected_candidate_jobs": (),
        "job_sync_results": (),
        "query_counts": (),
        "unique_job_pool_count": 0,
        "jobs_reviewed_count": 0,
        "added_count": 0,
        "updated_count": 0,
        "rejected_count": 0,
        "diagnostics": {},
    }
    defaults.update(overrides)
    from jobops_api.job_discovery.candidate_discovery.models import CandidateDiscoveryResult

    return CandidateDiscoveryResult(**defaults)
