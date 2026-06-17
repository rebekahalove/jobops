from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import jobops_api.job_discovery.service as job_discovery_service_module
from jobops_api.auth import SESSION_COOKIE_NAME, create_session_for_username, seed_initial_user
from jobops_api.db.models import Base, CandidateProfile, CandidateSavedJob, JobListing, JobSearchRun
from jobops_api.db.seed_profile import seed_public_profile
from jobops_api.db.session import get_db_session
from jobops_api.job_discovery import JobDiscoveryRequest, run_job_discovery
from jobops_api.job_discovery.candidate_discovery.models import CandidateDiscoveryResult, DbJobSearchPlan
from jobops_api.main import app
from jobops_api.security import INTERNAL_API_KEY_HEADER
from jobops_api.settings import Settings


def test_run_job_discovery_uses_db_backed_candidate_service(monkeypatch) -> None:
    engine = create_engine_for_job_discovery_tests()
    with Session(engine) as session:
        profile = seed_profile(session)
        session.commit()
        profile_id = profile.id
        profile_slug = profile.slug
        calls: dict[str, Any] = {}

        class FakeCandidateJobDiscoveryService:
            def __init__(self, *, session: Session, settings: Settings, connector: object) -> None:
                calls["service_session"] = session
                calls["settings"] = settings
                calls["connector"] = connector

            def run(
                self,
                request: JobDiscoveryRequest,
                *,
                candidate_profile: CandidateProfile,
                current_saved_jobs: list[dict[str, Any]],
                current_saved_companies: list[dict[str, Any]],
                target_context: dict[str, Any],
                private_profile_context: dict[str, Any],
                job_search_run_id: str | None = None,
            ) -> CandidateDiscoveryResult:
                calls["request"] = request
                calls["candidate_profile_id"] = candidate_profile.id
                calls["current_saved_jobs"] = current_saved_jobs
                calls["current_saved_companies"] = current_saved_companies
                calls["target_context"] = target_context
                calls["private_profile_context"] = private_profile_context
                calls["job_search_run_id"] = job_search_run_id
                return CandidateDiscoveryResult(
                    assistant_message="DB-backed discovery completed.",
                    job_search_run_id=job_search_run_id or "run-1",
                    search_plan=DbJobSearchPlan(),
                    selected_candidate_jobs=(),
                    updated_candidate_jobs=(),
                    rejected_candidate_jobs=(),
                    job_sync_results=(),
                    query_counts=(),
                    unique_job_pool_count=0,
                    jobs_reviewed_count=0,
                    added_count=0,
                    updated_count=0,
                    rejected_count=0,
                    diagnostics={
                        "jobSync": {},
                        "databaseQueries": {"uniqueJobPoolCount": 0, "queries": []},
                        "modelReview": {"jobsReviewedByModel": 0, "addedToCandidateJobsList": 0},
                    },
                )

        monkeypatch.setattr(job_discovery_service_module, "CandidateJobDiscoveryService", FakeCandidateJobDiscoveryService)
        monkeypatch.setattr(job_discovery_service_module, "should_prompt_for_discovery_targets", lambda *args, **kwargs: False)

        result = run_job_discovery(
            JobDiscoveryRequest(latest_user_message="find jobs", candidate_profile_slug=profile_slug),
            db_session=session,
            settings=make_test_settings(),
            connector=object(),
            candidate_profile=profile,
        )

    assert result.status_code == 200
    assert result.body["ok"] is True
    assert result.body["result"]["jobDiscoveryMode"] == "db_backed"
    assert result.body["result"]["sourceName"] == "synced_job_inventory"
    assert calls["candidate_profile_id"] == profile_id
    assert calls["request"].latest_user_message == "find jobs"


def test_start_job_discovery_run_reuses_recent_active_run() -> None:
    engine = create_engine_for_job_discovery_tests()
    with Session(engine) as session:
        profile = seed_profile(session)
        active_run = JobSearchRun(
            candidate_profile_id=profile.id,
            command_text="find jobs",
            search_plan_json={},
            provider_names=[],
            status="running",
            total_provider_results=0,
            candidate_pool_count=0,
            candidate_count_after_dedupe=0,
            replans_attempted=0,
            model_selected_count=0,
            saved_count=0,
            updated_existing_count=0,
            duplicate_count=0,
            skipped_count=0,
            provider_error_count=0,
            started_at=datetime.now(timezone.utc),
        )
        session.add(active_run)
        session.commit()
        active_run_id = active_run.id

        run, created = job_discovery_service_module.start_job_discovery_run(
            JobDiscoveryRequest(latest_user_message="find jobs", candidate_profile_slug=profile.slug),
            db_session=session,
            candidate_profile=profile,
            background_tasks=None,
        )
        run_id = run.id

    assert created is False
    assert run_id == active_run_id


def test_job_search_run_status_is_scoped_to_authenticated_candidate(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    engine = create_engine_for_job_discovery_tests()
    with Session(engine) as session:
        owner = seed_profile(session, slug="rebekah-love")
        other = seed_profile(session, slug="other-user", display_name="Other User")
        run = JobSearchRun(
            candidate_profile_id=other.id,
            command_text="find jobs",
            search_plan_json={},
            provider_names=[],
            status="completed",
            total_provider_results=0,
            candidate_pool_count=0,
            candidate_count_after_dedupe=0,
            replans_attempted=0,
            model_selected_count=0,
            saved_count=0,
            updated_existing_count=0,
            duplicate_count=0,
            skipped_count=0,
            provider_error_count=0,
        )
        session.add(run)
        session.commit()
        _ = owner
        run_id = run.id
    session_token = create_auth_session_token(engine)

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        client = TestClient(app)
        response = client.get(
            f"/v1/job-search-runs/{run_id}",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_add_job_listing_to_jobs_list_creates_saved_job_without_duplicates(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    engine = create_engine_for_job_discovery_tests()
    with Session(engine) as session:
        profile = seed_profile(session, slug="rebekah-love")
        listing = JobListing(
            id="listing-1",
            company_name="Example Civic",
            title="Applied AI Engineer",
            is_active=True,
        )
        session.add(listing)
        session.commit()
        listing_id = listing.id
        _ = profile
    session_token = create_auth_session_token(engine)

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        client = TestClient(app)
        first = client.post(
            f"/v1/jobs/from-listing/{listing_id}",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        second = client.post(
            f"/v1/jobs/from-listing/{listing_id}",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == 200
    assert first.json()["job"]["job_listing_id"] == listing_id
    assert first.json()["job"]["status"] == "new"
    assert second.status_code == 200
    with Session(engine) as session:
        saved_jobs = list(session.scalars(select(CandidateSavedJob).where(CandidateSavedJob.job_listing_id == listing_id)))
    assert len(saved_jobs) == 1


def create_engine_for_job_discovery_tests():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def seed_profile(
    session: Session,
    *,
    slug: str = "rebekah-love",
    display_name: str = "Rebekah Love",
) -> CandidateProfile:
    return seed_public_profile(
        session,
        {
            "slug": slug,
            "displayName": display_name,
            "headline": "Candidate profile setup in progress",
            "summary": "Verified public profile facts are being reviewed before publication.",
            "profileStatus": "draft",
        },
    )


def create_auth_session_token(engine) -> str:
    with Session(engine) as session:
        seed_initial_user(
            session,
            email="rebekah-love@jobops.local",
            username="rebekah-love",
            display_name="Rebekah Love",
            password="rebekah alpha password",
            password_reset_required=False,
        )
        _, raw_token = create_session_for_username(
            session,
            username="rebekah-love",
            password="rebekah alpha password",
        )
        session.commit()
        return raw_token


def make_test_settings() -> Settings:
    return Settings(
        repo_root="C:/Users/rasho/jobops",
        app_env="test",
        model_provider="mock",
        default_model="mock",
        cheap_model="mock",
        gemini_api_key=None,
        profile_intake_save_artifacts=False,
        profile_intake_save_raw_text=False,
        company_discovery_search_grounding_enabled=False,
        database_url=None,
    )
