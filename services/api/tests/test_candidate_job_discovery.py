from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import jobops_api.job_discovery.candidate_discovery.service as candidate_service_module
import jobops_api.job_discovery.service as job_discovery_service_module
from jobops_api.db.models import (
    Base,
    CandidateJobRejectionReason,
    CandidateProfile,
    CandidateSavedJob,
    JobListing,
    JobListingSource,
    JobSearchRun,
    Tenant,
)
from jobops_api.job_discovery.candidate_discovery.models import (
    DbJobSearchPlan,
    DbJobSearchQuery,
    JobReviewResult,
    RejectedJobDecision,
    SelectedJobDecision,
)
from jobops_api.job_discovery.candidate_discovery.query_builder import JobListingQueryBuilder
from jobops_api.job_discovery.candidate_discovery.repositories import CandidateJobRepository, ModelRejectionService
from jobops_api.job_discovery.candidate_discovery.service import CandidateJobDiscoveryService
from jobops_api.job_discovery.models import JobDiscoveryRequest
from jobops_api.job_discovery.service import run_job_discovery, serialize_saved_job
from jobops_api.model_connector import ModelResponse
from jobops_api.settings import Settings


def test_query_builder_new_to_candidate_excludes_existing_saved_listing(tmp_path: Path) -> None:
    engine = create_candidate_discovery_engine()
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        existing = create_job_listing(session, title="Senior AI Engineer", provider="greenhouse", provider_job_id="gh-1")
        fresh = create_job_listing(session, title="Staff AI Engineer", provider="adzuna", provider_job_id="adz-1")
        session.add(CandidateSavedJob(candidate_profile_id=profile.id, job_listing_id=existing.id, status="new"))
        session.commit()

        plan = DbJobSearchPlan(
            job_scope="new_to_candidate",
            queries=(DbJobSearchQuery(title_terms_any=("AI Engineer",), source_statuses_any=("active",), limit=10),),
        )
        jobs, query_counts = JobListingQueryBuilder(session).execute_plan(profile.id, plan)

    assert [job.id for job in jobs] == [fresh.id]
    assert query_counts == (("Synced job inventory search", 1),)


def test_query_builder_candidate_jobs_list_hides_model_rejected_by_default(tmp_path: Path) -> None:
    engine = create_candidate_discovery_engine()
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        visible = create_job_listing(session, title="Machine Learning Engineer", provider_job_id="visible")
        rejected = create_job_listing(session, title="Backend Engineer", provider_job_id="rejected")
        session.add_all(
            [
                CandidateSavedJob(candidate_profile_id=profile.id, job_listing_id=visible.id, status="new"),
                CandidateSavedJob(candidate_profile_id=profile.id, job_listing_id=rejected.id, status="model_rejected"),
            ]
        )
        session.commit()

        hidden_plan = DbJobSearchPlan(
            job_scope="candidate_jobs_list",
            queries=(DbJobSearchQuery(source_statuses_any=("active",), limit=10),),
        )
        visible_jobs, _ = JobListingQueryBuilder(session).execute_plan(profile.id, hidden_plan)
        include_rejected_plan = DbJobSearchPlan(
            job_scope="candidate_jobs_list",
            queries=(DbJobSearchQuery(source_statuses_any=("active",), include_model_rejected=True, limit=10),),
        )
        all_jobs, _ = JobListingQueryBuilder(session).execute_plan(profile.id, include_rejected_plan)

    assert {job.id for job in visible_jobs} == {visible.id}
    assert {job.id for job in all_jobs} == {visible.id, rejected.id}


def test_repository_records_rejection_reasons_and_reset_restores_job() -> None:
    engine = create_candidate_discovery_engine()
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        job = create_job_listing(session, title="Growth Product Manager", provider_job_id="pm-1")

        CandidateJobRepository(session).apply_review_result(
            candidate_profile_id=profile.id,
            job_search_run_id=None,
            review=JobReviewResult(
                user_visible_summary="Rejected one job.",
                rejected_jobs=(
                    RejectedJobDecision(
                        job_listing_id=job.id,
                        reason_codes=("industry_or_domain", "invalid-code"),
                        explanation="Not aligned with target industry.",
                    ),
                ),
            ),
        )
        session.commit()

        link = session.scalar(select(CandidateSavedJob).where(CandidateSavedJob.job_listing_id == job.id))
        assert link is not None
        assert link.status == "model_rejected"
        active_reasons = list(
            session.scalars(select(CandidateJobRejectionReason).where(CandidateJobRejectionReason.candidate_job_id == link.id))
        )
        assert {reason.reason_code for reason in active_reasons} == {"industry_or_domain", "other"}

        reset_count = ModelRejectionService(session).reset_model_rejections(
            candidate_profile_id=profile.id,
            reason_codes=None,
            reset_reason="Test reset.",
            reset_by="pytest",
        )
        session.commit()

        session.refresh(link)
        assert reset_count == 2
        assert link.status == "model_rejection_reset"
        assert all(not reason.active for reason in active_reasons)


def test_db_backed_service_saves_selected_and_persists_rejections(tmp_path: Path) -> None:
    engine = create_candidate_discovery_engine()
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        create_job_listing(session, title="AI Platform Engineer", provider_job_id="selected")
        create_job_listing(session, title="Sales Engineer", provider_job_id="rejected")
        session.commit()

        service = NoSyncCandidateJobDiscoveryService(
            session=session,
            settings=make_settings(tmp_path),
            planner=StaticPlanner(),
            reviewer=SelectFirstRejectSecondReviewer(),
        )
        result = service.run(
            JobDiscoveryRequest(latest_user_message="Find platform engineering jobs.", candidate_profile_slug=profile.slug),
            candidate_profile=profile,
            current_saved_jobs=[],
            current_saved_companies=[],
            target_context={},
            private_profile_context={},
        )
        session.commit()

        saved_links = list(session.scalars(select(CandidateSavedJob)).all())
        run = session.get(JobSearchRun, result.job_search_run_id)

    assert result.added_count == 1
    assert result.rejected_count == 1
    assert result.diagnostics["modelReview"]["rejectionReasonCounts"] == {"role_title": 1}
    assert {link.status for link in saved_links} == {"new", "model_rejected"}
    assert run is not None
    assert run.status == "completed"
    assert run.search_mode == "db_backed"


def test_run_job_discovery_uses_db_inventory_response_shape(tmp_path: Path, monkeypatch) -> None:
    engine = create_candidate_discovery_engine()
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        create_job_listing(session, title="AI Platform Engineer", provider_job_id="db-1")
        session.commit()

        monkeypatch.setattr(candidate_service_module.CandidateJobDiscoveryService, "ensure_inventory", lambda self, **kwargs: ())
        monkeypatch.setattr(job_discovery_service_module, "should_prompt_for_discovery_targets", lambda *args, **kwargs: False)
        monkeypatch.setattr(job_discovery_service_module, "create_model_connector", lambda config: DbPlanningConnector())
        monkeypatch.setattr(
            candidate_service_module.JobReviewSelector,
            "review",
            lambda self, *args, job_pool, **kwargs: JobReviewResult(
                user_visible_summary="I found one strong synced job.",
                selected_jobs=(SelectedJobDecision(job_listing_id=job_pool[0].job_listing_id, rationale="Strong match."),),
                diagnostics={"modelReviewCompleted": True},
            ),
        )
        result = run_job_discovery(
            JobDiscoveryRequest(latest_user_message="Find AI platform engineer jobs.", candidate_profile_slug=profile.slug),
            db_session=session,
            settings=make_settings(tmp_path),
            candidate_profile=profile,
        )

        assert result.status_code == 200
        assert result.body["ok"] is True
        payload = result.body["result"]
        assert payload["jobDiscoveryMode"] == "db_backed"
        assert payload["savedCount"] == 1
        assert len(payload["jobs"]) == 1
        assert payload["jobs"][0]["job_listing_id"] is not None
        assert payload["providerResultCount"] == 0
        assert payload["diagnostics"]["databaseQueries"]["uniqueJobPoolCount"] == 1
        assert payload["assistantMessage"]


def test_db_backed_saved_job_serializes_from_job_listing() -> None:
    engine = create_candidate_discovery_engine()
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        job = create_job_listing(
            session,
            title="Principal AI Engineer",
            provider="greenhouse",
            provider_job_id="serialize-1",
            canonical_url="https://boards.greenhouse.io/example/jobs/serialize-1",
        )
        link = CandidateSavedJob(candidate_profile_id=profile.id, job_listing_id=job.id, status="new")
        session.add(link)
        session.commit()
        session.refresh(link)

        payload = serialize_saved_job(link)

    assert payload["job_id"] is None
    assert payload["job_listing_id"] == job.id
    assert payload["title"] == "Principal AI Engineer"
    assert payload["job_url"] == "https://boards.greenhouse.io/example/jobs/serialize-1"
    assert payload["source_provider"] == "greenhouse"


class StaticPlanner:
    def plan(self, *args, **kwargs) -> DbJobSearchPlan:
        return DbJobSearchPlan(
            job_scope="new_to_candidate",
            queries=(DbJobSearchQuery(source_statuses_any=("active",), limit=10),),
            max_jobs_for_model_review=10,
        )


class DbPlanningConnector:
    def generate(self, request) -> ModelResponse:
        if request.task == "candidate_db_job_plan_critique":
            return ModelResponse(
                text=json.dumps({"valid": True, "issueCode": None, "issueMessage": None, "correctedPlan": None}),
                provider="fake",
                model="fake-db-critic",
            )
        assert request.task == "candidate_db_job_search_planning"
        return ModelResponse(
            text=json.dumps(
                {
                    "mode": "new_job_discovery",
                    "modeRationale": "The user asked to find jobs.",
                    "syncPlan": {
                        "useFollowedCompanyBoards": False,
                        "proposedAdzunaSignatures": [],
                        "existingAdzunaSignatureIdsToRefresh": [],
                        "rationale": "Use existing synced inventory in the test.",
                    },
                    "dbSearchPlan": {
                        "queries": [
                            {
                                "label": "Synced inventory test search",
                                "sourceStatusesAny": ["active"],
                                "limit": 10,
                            }
                        ]
                    },
                    "replanRules": {
                        "minJobPoolSize": 1,
                        "maxJobPoolSize": 10,
                        "maxJobsForModelReview": 10,
                    },
                }
            ),
            provider="fake",
            model="fake-db-planner",
        )


class SelectFirstRejectSecondReviewer:
    def review(self, *args, job_pool, **kwargs) -> JobReviewResult:
        return JobReviewResult(
            user_visible_summary="I found one strong synced job and held one back for review.",
            selected_jobs=(SelectedJobDecision(job_listing_id=job_pool[0].job_listing_id, rationale="Strong match."),),
            rejected_jobs=(
                RejectedJobDecision(
                    job_listing_id=job_pool[1].job_listing_id,
                    reason_codes=("role_title",),
                    explanation="Role does not match the requested platform focus.",
                ),
            ),
        )


class NoSyncCandidateJobDiscoveryService(CandidateJobDiscoveryService):
    def ensure_inventory(self, *, candidate_profile_id: str, plan: DbJobSearchPlan) -> tuple[Any, ...]:
        return ()


def create_candidate_discovery_engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def create_candidate_profile(session: Session) -> CandidateProfile:
    tenant = Tenant(name="Test Workspace", slug=f"test-{datetime.now(UTC).timestamp()}")
    profile = CandidateProfile(
        tenant=tenant,
        slug="rebekah-love",
        display_name="Rebekah Love",
        headline="AI platform candidate",
        summary="Private profile context for tests.",
        profile_status="draft",
    )
    session.add(profile)
    session.flush()
    return profile


def create_job_listing(
    session: Session,
    *,
    title: str,
    provider: str = "greenhouse",
    provider_job_id: str,
    canonical_url: str | None = None,
) -> JobListing:
    now = datetime.now(UTC)
    job = JobListing(
        title=title,
        company_name="Example Co",
        canonical_url=canonical_url or f"https://example.com/jobs/{provider_job_id}",
        apply_url=canonical_url or f"https://example.com/jobs/{provider_job_id}/apply",
        source_url=canonical_url or f"https://example.com/jobs/{provider_job_id}",
        location_display="Remote US",
        location_country="us",
        remote_work_mode="remote",
        employment_type="full_time",
        description_excerpt=f"{title} role.",
        full_description=f"{title} role building useful systems.",
        source_status="active",
        is_active=True,
        first_seen_at=now - timedelta(days=1),
        last_seen_at=now,
        source_updated_at=now,
    )
    source = JobListingSource(
        job_listing=job,
        source_provider=provider,
        provider_type="ats_board" if provider == "greenhouse" else "broad_search",
        provider_job_id=provider_job_id,
        source_result_id=provider_job_id,
        ats_provider=provider if provider == "greenhouse" else None,
        ats_board_token="example" if provider == "greenhouse" else None,
        source_url=job.source_url,
        apply_url=job.apply_url,
        canonical_url=job.canonical_url,
        source_query="AI Engineer",
        source_country="us",
        is_active=True,
        first_seen_at=now - timedelta(days=1),
        last_seen_at=now,
    )
    session.add(source)
    session.flush()
    return job


def make_settings(tmp_path: Path) -> Settings:
    return replace(
        Settings(
            app_env="test",
            model_provider="mock",
            default_model="mock-default",
            cheap_model="mock-cheap",
            gemini_api_key=None,
            profile_intake_save_artifacts=False,
            profile_intake_save_raw_text=False,
            company_discovery_search_grounding_enabled=False,
            database_url=None,
            repo_root=tmp_path,
        ),
        job_discovery_save_limit=25,
        job_discovery_candidate_pool_limit=100,
    )
