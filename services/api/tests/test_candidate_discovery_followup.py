from __future__ import annotations

import json
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

import jobops_api.job_discovery.candidate_discovery.planner as planner_module
import jobops_api.job_discovery.candidate_discovery.service as candidate_service_module
from jobops_api.db.models import JobSearchQueryRun, JobSyncRun, JobSyncSignature
from jobops_api.job_discovery.candidate_discovery.models import (
    DbJobSearchPlan,
    DbJobSearchQuery,
    JobReviewResult,
    RejectedJobDecision,
    SelectedJobDecision,
)
from jobops_api.job_discovery.candidate_discovery.planner import DbJobSearchPlanner, DbJobSearchPlanningError, parse_db_search_plan
from jobops_api.job_discovery.candidate_discovery.prompts import DB_JOB_SEARCH_PLAN_CRITIC_SYSTEM_PROMPT, DB_JOB_SEARCH_PLANNER_SYSTEM_PROMPT
from jobops_api.job_discovery.candidate_discovery.query_builder import JobListingQueryBuilder
from jobops_api.job_discovery.candidate_discovery.repositories import CandidateJobRepository, ModelRejectionService
from jobops_api.job_discovery.candidate_discovery.reviewer import JobReviewSelector, validate_review_result
from jobops_api.job_discovery.candidate_discovery.service import CandidateJobDiscoveryService
from jobops_api.job_discovery.models import JobDiscoveryRequest
from jobops_api.job_discovery.service import build_db_backed_job_discovery_result, list_jobs, serialize_job_search_run_status
from jobops_api.job_discovery.job_sync.models import JobSyncRequest, JobSyncResult
from jobops_api.job_discovery.job_sync.service import record_job_sync_run
from jobops_api.db.models import CandidateJobRejectionReason, CandidateSavedJob, JobSearchRun

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
    assert "new_job_discovery" in prompt
    assert "Do not call job results \"candidates.\"" in prompt
    assert "Return JSON only" in DB_JOB_SEARCH_PLAN_CRITIC_SYSTEM_PROMPT
    assert "correctedPlan" in DB_JOB_SEARCH_PLAN_CRITIC_SYSTEM_PROMPT


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
