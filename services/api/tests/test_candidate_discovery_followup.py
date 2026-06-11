from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from jobops_api.job_discovery.candidate_discovery.models import (
    DbJobSearchPlan,
    DbJobSearchQuery,
    JobReviewResult,
    RejectedJobDecision,
    SelectedJobDecision,
)
from jobops_api.job_discovery.candidate_discovery.planner import infer_scope
from jobops_api.job_discovery.candidate_discovery.prompts import DB_JOB_SEARCH_PLANNER_SYSTEM_PROMPT
from jobops_api.job_discovery.candidate_discovery.query_builder import JobListingQueryBuilder
from jobops_api.job_discovery.candidate_discovery.repositories import CandidateJobRepository, ModelRejectionService
from jobops_api.job_discovery.candidate_discovery.reviewer import JobReviewSelector, validate_review_result
from jobops_api.job_discovery.candidate_discovery.service import CandidateJobDiscoveryService
from jobops_api.job_discovery.models import JobDiscoveryRequest
from jobops_api.job_discovery.service import list_jobs
from jobops_api.db.models import CandidateJobRejectionReason, CandidateSavedJob

from test_candidate_job_discovery import (
    NoSyncCandidateJobDiscoveryService,
    StaticPlanner,
    create_candidate_discovery_engine,
    create_candidate_profile,
    create_job_listing,
    make_settings,
)


def test_deterministic_scope_inference_examples() -> None:
    cases = {
        "which jobs": "candidate_jobs_list",
        "what jobs": "candidate_jobs_list",
        "show me the jobs": "candidate_jobs_list",
        "show me my jobs": "candidate_jobs_list",
        "which saved jobs should I apply to": "candidate_jobs_list",
        "give me jobs to apply to": "new_to_candidate",
        "find jobs to apply to": "new_to_candidate",
        "show me some jobs": "new_to_candidate",
        "find new jobs": "new_to_candidate",
        "new and saved jobs": "all_accessible_jobs",
    }
    for message, expected_scope in cases.items():
        assert infer_scope(message) == expected_scope


def test_planner_prompt_contains_broadening_and_override_instructions() -> None:
    prompt = DB_JOB_SEARCH_PLANNER_SYSTEM_PROMPT

    assert "To broaden a search and increase results, remove or relax criteria" in prompt
    assert "Explicit latest-thread constraints outrank stored profile defaults" in prompt
    assert "Ask the user only before relaxing an explicit" in prompt


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
