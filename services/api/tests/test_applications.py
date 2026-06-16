from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from jobops_api.auth import SESSION_COOKIE_NAME, create_session_for_username, seed_initial_user
from jobops_api.db.models import (
    Application,
    ApplicationEvent,
    ApplicationMaterialBundle,
    ApplicationMaterialItem,
    Base,
    CandidateProfile,
    CandidateSavedJob,
    JobListing,
    JobListingSource,
)
from jobops_api.db.seed_profile import seed_public_profile
from jobops_api.db.session import get_db_session
from jobops_api.job_discovery.job_sync.providers.greenhouse.application_fields import (
    extract_application_fields_from_greenhouse_payload,
    summarize_greenhouse_application_requirements,
)
from jobops_api.main import app
from jobops_api.security import INTERNAL_API_KEY_HEADER


def test_application_tracker_crud_endpoints(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        profile = seed_public_profile(
            session,
            {
                "slug": "rebekah-love",
                "displayName": "Rebekah Love",
                "headline": "Candidate profile setup in progress",
                "summary": "Verified public profile facts are being reviewed before publication.",
                "profileStatus": "draft",
            },
        )
        profile_id = profile.id
        session.commit()

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        client = TestClient(app)
        session_token = create_auth_session_token(engine)

        create_response = client.post(
            "/v1/applications",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
            json={
                "candidate_profile_id": profile_id,
                "company_name": "Acme AI",
                "job_title": "Applied AI Engineer",
                "job_url": "https://example.com/jobs/applied-ai",
                "location": "Remote",
                "source": "manual",
                "date_applied": "2026-05-13",
                "status": "applied",
                "notes": "Submitted through company site.",
                "next_follow_up_date": "2026-05-20",
            },
        )
        assert create_response.status_code == 201
        created = create_response.json()
        assert created["company_name"] == "Acme AI"
        assert created["job_title"] == "Applied AI Engineer"
        assert created["status"] == "applied"

        list_response = client.get(
            f"/v1/applications?candidate_profile_id={profile_id}",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        assert list_response.status_code == 200
        applications = list_response.json()
        assert len(applications) == 1
        assert applications[0]["id"] == created["id"]

        status_response = client.patch(
            f"/v1/applications/{created['id']}/status",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
            json={"status": "interviewing"},
        )
        assert status_response.status_code == 200
        assert status_response.json()["status"] == "interviewing"

        applied_response = client.patch(
            f"/v1/applications/{created['id']}/status",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
            json={"status": "applied", "date_applied": date.today().isoformat()},
        )
        assert applied_response.status_code == 200
        assert applied_response.json()["status"] == "applied"
        assert applied_response.json()["date_applied"] == date.today().isoformat()

        event_response = client.post(
            f"/v1/applications/{created['id']}/events",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
            json={
                "event_type": "recruiter_screen_scheduled",
                "event_date": "2026-05-21",
                "notes": "Recruiter screen booked.",
                "metadata_json": {"channel": "email"},
            },
        )
        assert event_response.status_code == 201
        event = event_response.json()
        assert event["application_id"] == created["id"]
        assert event["metadata_json"] == {"channel": "email"}
    finally:
        app.dependency_overrides.clear()


def test_application_create_can_resolve_candidate_profile_slug(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
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
        )
        session.commit()

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        client = TestClient(app)
        session_token = create_auth_session_token(engine)
        response = client.post(
            "/v1/applications",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
            json={
                "candidate_profile_slug": "rebekah-love",
                "company_name": "Example Robotics",
                "job_title": "AI Product Engineer",
            },
        )

        assert response.status_code == 201
        with Session(engine) as session:
            profile_id = session.query(CandidateProfile.id).filter(CandidateProfile.slug == "rebekah-love").scalar()
        assert response.json()["candidate_profile_id"] == profile_id
    finally:
        app.dependency_overrides.clear()


def test_create_application_from_saved_job_links_canonical_job_and_prevents_duplicates(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    session_token = create_auth_session_token(engine)
    with Session(engine) as session:
        profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "rebekah-love"))
        assert profile is not None
        saved_job = create_saved_job(session, candidate_profile_id=profile.id)
        saved_job_id = saved_job.id
        session.commit()

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        client = TestClient(app)
        create_response = client.post(
            "/v1/applications",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
            json={"saved_job_id": saved_job_id, "status": "in_progress"},
        )
        assert create_response.status_code == 201
        created = create_response.json()
        assert created["status"] == "in_process"
        assert created["saved_job_id"] == saved_job_id
        assert created["company_name"] == "Example Civic"
        assert created["job_title"] == "Applied AI Engineer"
        assert created["job_url"] == "https://jobs.example.test/example-civic/apply"
        assert created["location"] == "Remote US"
        assert created["source"] == "greenhouse"
        assert created["date_applied"] is None
        assert created["source_provider"] == "greenhouse"
        assert created["fit_summary"] == "Matches applied AI and platform engineering goals."
        assert created["salary_text"] == "USD 150,000-180,000"
        assert created["remote_work_mode"] == "remote"
        assert created["employment_type"] == "Full-time"

        duplicate_response = client.post(
            "/v1/applications",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
            json={"saved_job_id": saved_job_id, "status": "in_progress"},
        )
        assert duplicate_response.status_code == 201
        assert duplicate_response.json()["id"] == created["id"]
        with Session(engine) as session:
            assert len(session.scalars(select(Application).where(Application.saved_job_id == saved_job_id)).all()) == 1
    finally:
        app.dependency_overrides.clear()


def test_create_application_from_synced_saved_job_without_canonical_posting(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    session_token = create_auth_session_token(engine)
    with Session(engine) as session:
        profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "rebekah-love"))
        assert profile is not None
        saved_job = create_synced_saved_job(session, candidate_profile_id=profile.id, with_application_fields=True)
        saved_job_id = saved_job.id
        session.commit()

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        client = TestClient(app)
        create_response = client.post(
            "/v1/applications",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
            json={"saved_job_id": saved_job_id, "status": "in_progress"},
        )
        assert create_response.status_code == 201
        created = create_response.json()
        assert created["status"] == "in_process"
        assert created["saved_job_id"] == saved_job_id
        assert created["company_name"] == "Synced Civic"
        assert created["job_title"] == "Synced Applied AI Engineer"
        assert created["job_url"] == "https://jobs.example.test/synced-civic/apply"
        assert created["location"] == "Remote US"
        assert created["source"] == "greenhouse"
        assert created["source_provider"] == "greenhouse"
        assert created["fit_summary"] == "Strong synced match."
        assert created["salary_text"] == "USD 155,000-185,000"
        assert created["remote_work_mode"] == "remote"
        assert created["employment_type"] == "Full-time"

        duplicate_response = client.post(
            "/v1/applications",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
            json={"saved_job_id": saved_job_id, "status": "in_progress"},
        )
        assert duplicate_response.status_code == 201
        assert duplicate_response.json()["id"] == created["id"]

        jobs_response = client.get(
            "/v1/jobs",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        assert jobs_response.status_code == 200
        [job_payload] = jobs_response.json()
        assert job_payload["id"] == saved_job_id
        assert job_payload["has_application"] is True
        assert job_payload["application_id"] == created["id"]
        assert job_payload["hasApplicationFields"] is True
        assert job_payload["requiredFieldCount"] == 4
        assert job_payload["shortAnswerQuestionCount"] == 1
        assert job_payload["requiresResume"] is True
        assert job_payload["requiresLinkedIn"] is True

        with Session(engine) as session:
            applications = session.scalars(select(Application).where(Application.saved_job_id == saved_job_id)).all()
            assert len(applications) == 1
    finally:
        app.dependency_overrides.clear()


def test_archiving_job_without_application_preserves_job_and_unrelated_applications(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    session_token = create_auth_session_token(engine)
    with Session(engine) as session:
        profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "rebekah-love"))
        assert profile is not None
        saved_job = create_saved_job(session, candidate_profile_id=profile.id)
        unrelated = Application(
            candidate_profile_id=profile.id,
            company_name="Manual Co",
            job_title="Manual Application",
            status="applied",
        )
        session.add(unrelated)
        session.commit()
        saved_job_id = saved_job.id
        unrelated_application_id = unrelated.id

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        client = TestClient(app)
        response = client.post(
            f"/v1/jobs/{saved_job_id}/archive",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["job_archived"] is True
        assert payload["application_archived"] is False
        with Session(engine) as session:
            saved_job = session.get(CandidateSavedJob, saved_job_id)
            assert saved_job is not None
            assert saved_job.archived_at is not None
            assert saved_job.archived_by_action == "user_archived_job"
            assert saved_job.job_listing is not None
            unrelated = session.get(Application, unrelated_application_id)
            assert unrelated is not None
            assert unrelated.archived_at is None
    finally:
        app.dependency_overrides.clear()


def test_favorite_and_unfavorite_job_updates_saved_job_status(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    session_token = create_auth_session_token(engine)
    with Session(engine) as session:
        profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "rebekah-love"))
        assert profile is not None
        saved_job = create_saved_job(session, candidate_profile_id=profile.id)
        saved_job.status = "new"
        session.commit()
        saved_job_id = saved_job.id

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        client = TestClient(app)
        favorite_response = client.post(
            f"/v1/jobs/{saved_job_id}/favorite",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        assert favorite_response.status_code == 200
        assert favorite_response.json()["job"]["status"] == "saved"

        unfavorite_response = client.post(
            f"/v1/jobs/{saved_job_id}/unfavorite",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        assert unfavorite_response.status_code == 200
        assert unfavorite_response.json()["job"]["status"] == "new"
    finally:
        app.dependency_overrides.clear()


def test_batch_favorite_jobs_updates_current_user_only_and_reports_missing(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    session_token = create_auth_session_token(engine)
    create_auth_session_token(
        engine,
        username="other-user",
        email="other-user@jobops.local",
        display_name="Other User",
        password="other user alpha password",
    )
    with Session(engine) as session:
        profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "rebekah-love"))
        other_profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "other-user"))
        assert profile is not None
        assert other_profile is not None
        first_job = create_saved_job(session, candidate_profile_id=profile.id, title="First Favorite Batch Job")
        second_job = create_saved_job(session, candidate_profile_id=profile.id, title="Second Favorite Batch Job")
        second_job.status = "saved"
        other_job = create_saved_job(session, candidate_profile_id=other_profile.id, title="Other User Job")
        session.commit()
        first_job_id = first_job.id
        second_job_id = second_job.id
        other_job_id = other_job.id

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        client = TestClient(app)
        response = client.post(
            "/v1/jobs/favorite-batch",
            json={"savedJobIds": [first_job_id, second_job_id, other_job_id, "missing-job-id", first_job_id]},
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["requested_count"] == 4
        assert payload["updated_count"] == 1
        assert payload["already_favorite_count"] == 1
        assert payload["not_found_count"] == 2
        assert payload["updated_job_ids"] == [first_job_id]
        assert payload["already_favorite_job_ids"] == [second_job_id]
        assert set(payload["not_found_job_ids"]) == {other_job_id, "missing-job-id"}

        repeat_response = client.post(
            "/v1/jobs/favorite-batch",
            json={"saved_job_ids": [first_job_id, second_job_id]},
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        assert repeat_response.status_code == 200
        repeat_payload = repeat_response.json()
        assert repeat_payload["updated_count"] == 0
        assert repeat_payload["already_favorite_count"] == 2

        with Session(engine) as session:
            assert session.get(CandidateSavedJob, first_job_id).status == "saved"
            assert session.get(CandidateSavedJob, second_job_id).status == "saved"
            assert session.get(CandidateSavedJob, other_job_id).status == "new"
    finally:
        app.dependency_overrides.clear()


def test_saved_job_serialization_separates_provider_source_and_provenance(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    session_token = create_auth_session_token(engine)
    with Session(engine) as session:
        profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "rebekah-love"))
        assert profile is not None
        saved_job = create_saved_job(
            session,
            candidate_profile_id=profile.id,
            full_description="Full provider job description with responsibilities and qualifications.",
            description_excerpt="Generated or provider excerpt.",
        )
        session.commit()
        saved_job_id = saved_job.id

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        client = TestClient(app)
        response = client.get(
            "/v1/jobs",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        assert response.status_code == 200
        [payload] = response.json()
        assert payload["id"] == saved_job_id
        assert payload["job_listing_id"]
        assert payload["source"] == "greenhouse"
        assert payload["source_provider"] == "greenhouse"
        assert payload["provenance"] == "job_sync"
        assert payload["source_result_id"]
        assert payload["source_query"] == "Company careers"
        assert payload["full_description"] == "Full provider job description with responsibilities and qualifications."
        assert payload["description_html"] is None
        assert payload["fit_summary"] == "Matches applied AI and platform engineering goals."
        assert payload["posting_date"] == "2026-05-20"
        assert payload["location"] == "Remote US"
        assert payload["remote_work_mode"] == "remote"
        assert payload["employment_type"] == "Full-time"
        assert payload["salary_text"] == "USD 150,000-180,000"
    finally:
        app.dependency_overrides.clear()


def test_saved_job_serialization_includes_sanitized_provider_description_html(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    session_token = create_auth_session_token(engine)
    with Session(engine) as session:
        profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "rebekah-love"))
        assert profile is not None
        saved_job = create_saved_job(session, candidate_profile_id=profile.id)
        source = session.scalar(select(JobListingSource).where(JobListingSource.job_listing_id == saved_job.job_listing_id))
        assert source is not None
        source.raw_metadata_json = {
            "content": (
                '&lt;h2&gt;About Hightouch&lt;/h2&gt;'
                '&lt;p&gt;Build &lt;strong&gt;agentic marketing&lt;/strong&gt; systems.&lt;/p&gt;'
                '&lt;ul&gt;&lt;li&gt;Own product development&lt;/li&gt;&lt;/ul&gt;'
                '&lt;script&gt;alert("bad")&lt;/script&gt;'
                '&lt;a href="javascript:alert(1)" onclick="bad()"&gt;Unsafe&lt;/a&gt;'
                '&lt;a href="https://jobs.example.test/details"&gt;Details&lt;/a&gt;'
            )
        }
        session.commit()

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        client = TestClient(app)
        response = client.get(
            "/v1/jobs",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        assert response.status_code == 200
        [payload] = response.json()
        assert payload["description_html"]
        assert "<h2>About Hightouch</h2>" in payload["description_html"]
        assert "<strong>agentic marketing</strong>" in payload["description_html"]
        assert "<li>Own product development</li>" in payload["description_html"]
        assert 'href="https://jobs.example.test/details"' in payload["description_html"]
        assert "script" not in payload["description_html"].casefold()
        assert "javascript:" not in payload["description_html"].casefold()
        assert "onclick" not in payload["description_html"].casefold()
    finally:
        app.dependency_overrides.clear()


def test_archiving_and_restoring_job_cascades_only_job_archived_application(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    session_token = create_auth_session_token(engine)
    with Session(engine) as session:
        profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "rebekah-love"))
        assert profile is not None
        saved_job = create_saved_job(session, candidate_profile_id=profile.id)
        application = Application(
            candidate_profile_id=profile.id,
            saved_job_id=saved_job.id,
            company_name="Example Civic",
            job_title="Applied AI Engineer",
            status="in_process",
            notes="Preserve me.",
        )
        session.add(application)
        session.flush()
        bundle = ApplicationMaterialBundle(
            application_id=application.id,
            candidate_profile_id=profile.id,
            status="generated",
            source_context_snapshot={"safe": True},
        )
        session.add(bundle)
        session.flush()
        session.add(
            ApplicationMaterialItem(
                bundle_id=bundle.id,
                material_type="cover_letter",
                title="Cover Letter",
                content="Preserved material.",
                sort_order=0,
            )
        )
        session.add(ApplicationEvent(application_id=application.id, event_type="note", event_date=date.today(), notes="Preserved event."))
        session.commit()
        saved_job_id = saved_job.id
        application_id = application.id

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        client = TestClient(app)
        archive_response = client.post(
            f"/v1/jobs/{saved_job_id}/archive",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        assert archive_response.status_code == 200
        assert archive_response.json()["application_archived"] is True
        assert "linked application archived" in archive_response.json()["message"].lower()

        with Session(engine) as session:
            application = session.get(Application, application_id)
            assert application is not None
            assert application.archived_at is not None
            assert application.archived_by_action == "user_archived_job"
            assert application.status == "in_process"
            assert session.scalar(select(ApplicationMaterialBundle).where(ApplicationMaterialBundle.application_id == application_id)) is not None
            assert session.scalar(select(ApplicationEvent).where(ApplicationEvent.application_id == application_id)) is not None

        restore_response = client.post(
            f"/v1/jobs/{saved_job_id}/restore",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        assert restore_response.status_code == 200
        assert restore_response.json()["job_restored"] is True
        assert restore_response.json()["application_restored"] is True

        with Session(engine) as session:
            saved_job = session.get(CandidateSavedJob, saved_job_id)
            application = session.get(Application, application_id)
            assert saved_job is not None
            assert application is not None
            assert saved_job.archived_at is None
            assert application.archived_at is None
            assert application.status == "in_process"
            assert session.scalar(select(ApplicationMaterialItem)) is not None
    finally:
        app.dependency_overrides.clear()


def test_restoring_job_does_not_restore_separately_archived_application(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    session_token = create_auth_session_token(engine)
    with Session(engine) as session:
        profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "rebekah-love"))
        assert profile is not None
        saved_job = create_saved_job(session, candidate_profile_id=profile.id)
        application = Application(
            candidate_profile_id=profile.id,
            saved_job_id=saved_job.id,
            company_name="Example Civic",
            job_title="Applied AI Engineer",
            status="in_process",
        )
        session.add(application)
        session.commit()
        saved_job_id = saved_job.id
        application_id = application.id

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        client = TestClient(app)
        archive_app = client.post(
            f"/v1/applications/{application_id}/archive",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        assert archive_app.status_code == 200
        archive_job = client.post(
            f"/v1/jobs/{saved_job_id}/archive",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        assert archive_job.status_code == 200

        restore_job = client.post(
            f"/v1/jobs/{saved_job_id}/restore",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        assert restore_job.status_code == 200
        payload = restore_job.json()
        assert payload["job_restored"] is True
        assert payload["application_restored"] is False
        assert payload["application_restore_skipped"] is True
        assert payload["application_archived_by_action"] == "user_archived_application"

        with Session(engine) as session:
            saved_job = session.get(CandidateSavedJob, saved_job_id)
            application = session.get(Application, application_id)
            assert saved_job is not None
            assert application is not None
            assert saved_job.archived_at is None
            assert application.archived_at is not None
    finally:
        app.dependency_overrides.clear()


def test_rejected_and_withdrawn_auto_archive_and_restore_preserves_status(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    session_token = create_auth_session_token(engine)
    with Session(engine) as session:
        profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "rebekah-love"))
        assert profile is not None
        rejected = Application(candidate_profile_id=profile.id, company_name="Reject Co", job_title="Role", status="applied")
        withdrawn = Application(candidate_profile_id=profile.id, company_name="Withdraw Co", job_title="Role", status="applied")
        session.add_all([rejected, withdrawn])
        session.commit()
        rejected_id = rejected.id
        withdrawn_id = withdrawn.id

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        client = TestClient(app)
        rejected_response = client.post(
            f"/v1/applications/{rejected_id}/reject",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        withdrawn_response = client.post(
            f"/v1/applications/{withdrawn_id}/withdraw",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        assert rejected_response.status_code == 200
        assert withdrawn_response.status_code == 200
        assert rejected_response.json()["application_archived"] is True
        assert withdrawn_response.json()["application_archived"] is True
        assert rejected_response.json()["application"]["status"] == "rejected"
        assert rejected_response.json()["application"]["date_applied"] == date.today().isoformat()
        assert withdrawn_response.json()["application"]["status"] == "withdrawn"
        assert withdrawn_response.json()["application"]["date_applied"] == date.today().isoformat()

        restore_response = client.post(
            f"/v1/applications/{rejected_id}/restore",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        assert restore_response.status_code == 200
        assert restore_response.json()["application_restored"] is True
        assert restore_response.json()["application"]["status"] == "rejected"
        assert restore_response.json()["application"]["archived_at"] is None

        with Session(engine) as session:
            rejected = session.get(Application, rejected_id)
            withdrawn = session.get(Application, withdrawn_id)
            assert rejected is not None
            assert withdrawn is not None
            assert rejected.status == "rejected"
            assert rejected.archived_at is None
            assert rejected.date_applied == date.today()
            assert withdrawn.status == "withdrawn"
            assert withdrawn.archived_at is not None
            assert withdrawn.archived_by_action == "status_withdrawn"
            assert withdrawn.date_applied == date.today()
            rejected_events = session.scalars(
                select(ApplicationEvent.event_type).where(ApplicationEvent.application_id == rejected_id).order_by(ApplicationEvent.created_at.asc())
            ).all()
            withdrawn_events = session.scalars(
                select(ApplicationEvent.event_type).where(ApplicationEvent.application_id == withdrawn_id).order_by(ApplicationEvent.created_at.asc())
            ).all()
            assert rejected_events == ["rejected"]
            assert withdrawn_events == ["withdrawn"]
    finally:
        app.dependency_overrides.clear()


def test_reopen_terminal_application_clears_terminal_status_date_and_archive(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    session_token = create_auth_session_token(engine)
    with Session(engine) as session:
        profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "rebekah-love"))
        assert profile is not None
        application = Application(
            candidate_profile_id=profile.id,
            company_name="Withdraw Co",
            job_title="Role",
            status="withdrawn",
            date_applied=date.today(),
            archived_at=datetime.now(timezone.utc),
            archived_reason="Application marked withdrawn.",
            archived_by_action="status_withdrawn",
        )
        session.add(application)
        session.commit()
        application_id = application.id

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        client = TestClient(app)
        response = client.post(
            f"/v1/applications/{application_id}/reopen",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["application"]["status"] == "applied"
        assert payload["application"]["date_applied"] is None
        assert payload["application"]["archived_at"] is None
        assert payload["application_restored"] is True

        with Session(engine) as session:
            application = session.get(Application, application_id)
            assert application is not None
            assert application.status == "applied"
            assert application.date_applied is None
            assert application.archived_at is None
            event = session.scalar(select(ApplicationEvent).where(ApplicationEvent.application_id == application_id))
            assert event is not None
            assert event.event_type == "terminal_status_reset"
            assert event.metadata_json["previous_terminal_status"] == "withdrawn"
    finally:
        app.dependency_overrides.clear()


def test_reject_and_withdraw_require_applied_status(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    session_token = create_auth_session_token(engine)
    with Session(engine) as session:
        profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "rebekah-love"))
        assert profile is not None
        application = Application(candidate_profile_id=profile.id, company_name="Reject Co", job_title="Role", status="in_process")
        session.add(application)
        session.commit()
        application_id = application.id

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        client = TestClient(app)
        reject_response = client.post(
            f"/v1/applications/{application_id}/reject",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        assert reject_response.status_code == 409
        assert "marked applied" in reject_response.json()["detail"]

        withdraw_response = client.patch(
            f"/v1/applications/{application_id}/status",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
            json={"status": "withdrawn"},
        )
        assert withdraw_response.status_code == 409

        with Session(engine) as session:
            application = session.get(Application, application_id)
            assert application is not None
            assert application.status == "in_process"
            assert application.archived_at is None
    finally:
        app.dependency_overrides.clear()


def test_job_and_application_list_responses_include_archive_and_linked_application_shape(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    session_token = create_auth_session_token(engine)
    with Session(engine) as session:
        profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "rebekah-love"))
        assert profile is not None
        saved_job = create_saved_job(session, candidate_profile_id=profile.id)
        application = Application(
            candidate_profile_id=profile.id,
            saved_job_id=saved_job.id,
            company_name="Example Civic",
            job_title="Applied AI Engineer",
            status="in_process",
        )
        session.add(application)
        session.commit()
        application_id = application.id

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        client = TestClient(app)
        jobs_response = client.get(
            "/v1/jobs",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        assert jobs_response.status_code == 200
        job_payload = jobs_response.json()[0]
        assert job_payload["has_application"] is True
        assert job_payload["application_id"] == application_id
        assert job_payload["application_status"] == "in_process"
        assert "archived_reason" in job_payload
        assert "archived_by_action" in job_payload

        applications_response = client.get(
            "/v1/applications",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        assert applications_response.status_code == 200
        application_payload = applications_response.json()[0]
        assert application_payload["status"] == "in_process"
        assert application_payload["archived_at"] is None
        assert "archived_reason" in application_payload
        assert application_payload["job_title"] == "Applied AI Engineer"
        assert application_payload["company_name"] == "Example Civic"
    finally:
        app.dependency_overrides.clear()


def test_get_application_detail_returns_owned_application_with_archive_metadata_and_materials(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    session_token = create_auth_session_token(engine)
    with Session(engine) as session:
        profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "rebekah-love"))
        assert profile is not None
        saved_job = create_saved_job(session, candidate_profile_id=profile.id)
        application = Application(
            candidate_profile_id=profile.id,
            saved_job_id=saved_job.id,
            company_name="Example Civic",
            job_title="Applied AI Engineer",
            job_url="https://jobs.example.test/example-civic/applied-ai",
            location="Remote US",
            source="Company careers",
            status="in_process",
            notes="Tailor materials around platform AI.",
            archived_reason="Application archived by user.",
            archived_by_action="user_archived_application",
        )
        session.add(application)
        session.flush()
        bundle = ApplicationMaterialBundle(
            application_id=application.id,
            candidate_profile_id=profile.id,
            status="generated",
            model_provider="mock",
            model_name="mock-default",
            source_context_snapshot={"safe": True},
        )
        session.add(bundle)
        session.flush()
        session.add(
            ApplicationMaterialItem(
                bundle_id=bundle.id,
                material_type="cover_letter",
                title="Cover Letter",
                content="Dear Example Civic team,",
                sort_order=0,
            )
        )
        session.commit()
        application_id = application.id
        saved_job_id = saved_job.id
        bundle_id = bundle.id

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        client = TestClient(app)
        response = client.get(
            f"/v1/applications/{application_id}",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["id"] == application_id
        assert payload["company_name"] == "Example Civic"
        assert payload["job_title"] == "Applied AI Engineer"
        assert payload["notes"] == "Tailor materials around platform AI."
        assert payload["archived_reason"] == "Application archived by user."
        assert payload["archived_by_action"] == "user_archived_application"
        assert payload["saved_job_id"] == saved_job_id
        assert payload["source_provider"] == "greenhouse"
        assert payload["apply_url"] == "https://jobs.example.test/example-civic/apply"
        assert payload["latest_material_bundle"]["id"] == bundle_id
        assert payload["latest_material_bundle"]["items"][0]["title"] == "Cover Letter"
    finally:
        app.dependency_overrides.clear()


def test_get_application_detail_rejects_other_users_application(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    rebekah_token = create_auth_session_token(engine)
    create_auth_session_token(
        engine,
        username="other-user",
        email="other-user@jobops.local",
        display_name="Other User",
        password="other user alpha password",
    )
    with Session(engine) as session:
        other_profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "other-user"))
        assert other_profile is not None
        application = Application(
            candidate_profile_id=other_profile.id,
            company_name="Private Co",
            job_title="Private Role",
            status="in_process",
            notes="Other user's private notes.",
        )
        session.add(application)
        session.commit()
        application_id = application.id

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        client = TestClient(app)
        response = client.get(
            f"/v1/applications/{application_id}",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: rebekah_token},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Application not found."
    finally:
        app.dependency_overrides.clear()


def test_create_application_from_another_users_saved_job_is_forbidden(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    rebekah_token = create_auth_session_token(engine)
    create_auth_session_token(
        engine,
        username="other-user",
        email="other-user@jobops.local",
        display_name="Other User",
        password="other user alpha password",
    )

    with Session(engine) as session:
        other_profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "other-user"))
        assert other_profile is not None
        saved_job = create_saved_job(session, candidate_profile_id=other_profile.id, title="Private Role")
        other_saved_job_id = saved_job.id
        session.commit()

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        client = TestClient(app)
        response = client.post(
            "/v1/applications",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: rebekah_token},
            json={"saved_job_id": other_saved_job_id, "status": "in_progress"},
        )
        assert response.status_code == 404
        with Session(engine) as session:
            assert session.scalar(select(Application)) is None
    finally:
        app.dependency_overrides.clear()


def test_generate_application_materials_creates_bundle_items_and_uses_full_description(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    monkeypatch.setenv("JOBOPS_LLM_PROVIDER", "mock")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    session_token = create_auth_session_token(engine)
    with Session(engine) as session:
        profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "rebekah-love"))
        assert profile is not None
        saved_job = create_saved_job(
            session,
            candidate_profile_id=profile.id,
            full_description="Full stored job description with platform AI workflows, RAG evaluation, and production ownership.",
            description_excerpt="Short excerpt only.",
        )
        application = Application(
            candidate_profile_id=profile.id,
            saved_job_id=saved_job.id,
            company_name="Example Civic",
            job_title="Applied AI Engineer",
            job_url="https://jobs.example.test/example-civic/applied-ai",
            status="in_progress",
            notes="Emphasize evaluation systems.",
        )
        session.add(application)
        session.commit()
        application_id = application.id

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        client = TestClient(app)
        response = client.post(
            f"/v1/applications/{application_id}/materials/generate",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        assert response.status_code == 201
        payload = response.json()
        assert payload["ok"] is True
        assert payload["bundle"]["application_id"] == application_id
        assert len(payload["bundle"]["items"]) >= 3
        assert payload["contextManifest"]["fullJobDescriptionIncluded"] is True
        assert payload["contextManifest"]["jobDescriptionSource"] == "synced_full_stored"

        with Session(engine) as session:
            bundle = session.scalar(select(ApplicationMaterialBundle).where(ApplicationMaterialBundle.application_id == application_id))
            assert bundle is not None
            assert bundle.model_provider == "mock"
            assert bundle.source_context_snapshot["manifest"]["jobDescriptionSource"] == "synced_full_stored"
            assert "Full stored job description" in bundle.source_context_snapshot["context"]["jobPosting"]["jobDescription"]
            assert session.scalar(select(ApplicationMaterialItem).where(ApplicationMaterialItem.bundle_id == bundle.id)) is not None

        list_response = client.get(
            "/v1/applications",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        assert list_response.status_code == 200
        listed = list_response.json()[0]
        assert listed["latest_material_bundle"]["id"] == payload["bundle"]["id"]

        materials_response = client.get(
            f"/v1/applications/{application_id}/materials",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        assert materials_response.status_code == 200
        assert materials_response.json()[0]["id"] == payload["bundle"]["id"]
    finally:
        app.dependency_overrides.clear()


def test_generate_application_materials_includes_synced_application_fields(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    monkeypatch.setenv("JOBOPS_LLM_PROVIDER", "mock")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    session_token = create_auth_session_token(engine)
    with Session(engine) as session:
        profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "rebekah-love"))
        assert profile is not None
        saved_job = create_synced_saved_job(session, candidate_profile_id=profile.id, with_application_fields=True)
        application = Application(
            candidate_profile_id=profile.id,
            saved_job_id=saved_job.id,
            company_name="Synced Civic",
            job_title="Synced Applied AI Engineer",
            job_url="https://jobs.example.test/synced-civic/apply",
            status="in_progress",
            notes="Draft against the actual ATS fields.",
        )
        session.add(application)
        session.commit()
        application_id = application.id

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        client = TestClient(app)
        response = client.post(
            f"/v1/applications/{application_id}/materials/generate",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        assert response.status_code == 201
        payload = response.json()
        assert payload["contextManifest"]["jobDescriptionSource"] == "synced_full_stored"
        assert payload["contextManifest"]["applicationFieldsIncluded"] is True
        assert payload["contextManifest"]["applicationFieldsProvider"] == "greenhouse"
        assert payload["contextManifest"]["applicationFieldsRequiredCount"] == 4
        assert payload["contextManifest"]["applicationFieldsShortAnswerCount"] == 1
        assert "resume" in payload["contextManifest"]["applicationFieldsDetectedMaterials"]

        with Session(engine) as session:
            bundle = session.scalar(select(ApplicationMaterialBundle).where(ApplicationMaterialBundle.application_id == application_id))
            assert bundle is not None
            snapshot = bundle.source_context_snapshot
            assert snapshot["context"]["applicationRequirements"]["requiresResume"] is True
            short_answer_labels = [
                question["label"]
                for question in snapshot["context"]["applicationRequirements"]["shortAnswerQuestions"]
            ]
            assert "Resume" not in short_answer_labels
            assert short_answer_labels == ["Why do you want this role?"]
            short_answers = [
                item.content
                for item in bundle.items
                if item.material_type == "short_application_answers"
            ]
            checklist = [
                item.content
                for item in bundle.items
                if item.material_type == "application_checklist"
            ]
            assert short_answers and "Why do you want this role?" in short_answers[0]
            assert checklist and "Resume" in checklist[0]
    finally:
        app.dependency_overrides.clear()


def test_generate_application_materials_creates_new_bundle_version(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    monkeypatch.setenv("JOBOPS_LLM_PROVIDER", "mock")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    session_token = create_auth_session_token(engine)
    with Session(engine) as session:
        profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "rebekah-love"))
        assert profile is not None
        application = Application(
            candidate_profile_id=profile.id,
            company_name="Manual Co",
            job_title="AI Workflow Engineer",
            status="in_progress",
            notes="Manual application without a linked job.",
        )
        session.add(application)
        session.commit()
        application_id = application.id

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        client = TestClient(app)
        first = client.post(
            f"/v1/applications/{application_id}/materials/generate",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        second = client.post(
            f"/v1/applications/{application_id}/materials/generate",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json()["bundle"]["id"] != second.json()["bundle"]["id"]
        with Session(engine) as session:
            bundles = session.scalars(select(ApplicationMaterialBundle).where(ApplicationMaterialBundle.application_id == application_id)).all()
            assert len(bundles) == 2
    finally:
        app.dependency_overrides.clear()


def test_generate_application_materials_falls_back_to_description_excerpt(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    monkeypatch.setenv("JOBOPS_LLM_PROVIDER", "mock")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    session_token = create_auth_session_token(engine)
    with Session(engine) as session:
        profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "rebekah-love"))
        assert profile is not None
        saved_job = create_saved_job(
            session,
            candidate_profile_id=profile.id,
            full_description=None,
            description_excerpt="Excerpt fallback about AI workflow automation.",
        )
        application = Application(
            candidate_profile_id=profile.id,
            saved_job_id=saved_job.id,
            company_name="Example Civic",
            job_title="Applied AI Engineer",
            status="in_progress",
            notes="",
        )
        session.add(application)
        session.commit()
        application_id = application.id

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        client = TestClient(app)
        response = client.post(
            f"/v1/applications/{application_id}/materials/generate",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        assert response.status_code == 201
        assert response.json()["contextManifest"]["fullJobDescriptionIncluded"] is False
        assert response.json()["contextManifest"]["jobDescriptionSource"] == "synced_excerpt_fallback"
        with Session(engine) as session:
            bundle = session.scalar(select(ApplicationMaterialBundle).where(ApplicationMaterialBundle.application_id == application_id))
            assert bundle is not None
            assert bundle.source_context_snapshot["context"]["jobPosting"]["jobDescription"] == "Excerpt fallback about AI workflow automation."
    finally:
        app.dependency_overrides.clear()


def test_application_materials_are_private_to_owner(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    monkeypatch.setenv("JOBOPS_LLM_PROVIDER", "mock")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    rebekah_token = create_auth_session_token(engine)
    create_auth_session_token(
        engine,
        username="other-user",
        email="other-user@jobops.local",
        display_name="Other User",
        password="other user alpha password",
    )
    with Session(engine) as session:
        other_profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "other-user"))
        assert other_profile is not None
        application = Application(
            candidate_profile_id=other_profile.id,
            company_name="Private Co",
            job_title="Private Role",
            status="in_progress",
            notes="Other user's notes.",
        )
        session.add(application)
        session.commit()
        application_id = application.id

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        client = TestClient(app)
        generate_response = client.post(
            f"/v1/applications/{application_id}/materials/generate",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: rebekah_token},
        )
        assert generate_response.status_code == 404

        read_response = client.get(
            f"/v1/applications/{application_id}/materials",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: rebekah_token},
        )
        assert read_response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_mark_applied_defaults_date_and_records_event(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    session_token = create_auth_session_token(engine)
    with Session(engine) as session:
        profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "rebekah-love"))
        assert profile is not None
        application = Application(
            candidate_profile_id=profile.id,
            company_name="Acme AI",
            job_title="Applied AI Engineer",
            status="in_progress",
            notes="",
        )
        session.add(application)
        session.commit()
        application_id = application.id

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        client = TestClient(app)
        response = client.patch(
            f"/v1/applications/{application_id}/status",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
            json={"status": "applied"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "applied"
        assert payload["date_applied"] == date.today().isoformat()
        with Session(engine) as session:
            event = session.scalar(select(ApplicationEvent).where(ApplicationEvent.application_id == application_id))
            assert event is not None
            assert event.event_type == "applied"
            assert event.event_date == date.today()
    finally:
        app.dependency_overrides.clear()


def create_saved_job(
    session: Session,
    *,
    candidate_profile_id: str,
    title: str = "Applied AI Engineer",
    full_description: str | None = None,
    description_excerpt: str | None = None,
) -> CandidateSavedJob:
    job_listing = JobListing(
        title=title,
        company_name="Example Civic",
        canonical_url="https://jobs.example.test/example-civic/applied-ai",
        apply_url="https://jobs.example.test/example-civic/apply",
        source_url="https://jobs.example.test/example-civic/applied-ai",
        location_display="Remote US",
        location_country="us",
        remote_work_mode="remote",
        employment_type="Full-time",
        salary_text="USD 150,000-180,000",
        full_description=full_description,
        description_excerpt=description_excerpt,
        posting_date=date(2026, 5, 20),
        source_status="active",
    )
    session.add(job_listing)
    session.flush()
    session.add(
        JobListingSource(
            job_listing_id=job_listing.id,
            source_provider="greenhouse",
            provider_type="ats",
            provider_job_id=f"example-civic-{title.lower().replace(' ', '-')}",
            source_result_id=f"example-civic-{title.lower().replace(' ', '-')}",
            source_query="Company careers",
            source_url="https://jobs.example.test/example-civic/applied-ai",
            apply_url="https://jobs.example.test/example-civic/apply",
            canonical_url="https://jobs.example.test/example-civic/applied-ai",
            is_active=True,
            raw_metadata_json={},
        )
    )
    saved_job = CandidateSavedJob(
        candidate_profile_id=candidate_profile_id,
        job_listing_id=job_listing.id,
        fit_summary="Matches applied AI and platform engineering goals.",
    )
    session.add(saved_job)
    session.flush()
    return saved_job


def create_synced_saved_job(
    session: Session,
    *,
    candidate_profile_id: str,
    with_application_fields: bool = False,
) -> CandidateSavedJob:
    job_listing = JobListing(
        title="Synced Applied AI Engineer",
        company_name="Synced Civic",
        canonical_url="https://jobs.example.test/synced-civic/applied-ai",
        apply_url="https://jobs.example.test/synced-civic/apply",
        source_url="https://jobs.example.test/synced-civic/applied-ai",
        location_display="Remote US",
        location_country="us",
        remote_work_mode="remote",
        employment_type="Full-time",
        salary_text="USD 155,000-185,000",
        posting_date=date(2026, 5, 22),
        source_status="active",
        full_description="Synced full job description about applied AI systems, user workflows, and product ownership.",
        description_excerpt="Synced excerpt.",
    )
    session.add(job_listing)
    session.flush()
    session.add(
        JobListingSource(
            job_listing_id=job_listing.id,
            source_provider="greenhouse",
            provider_type="ats",
            provider_job_id="synced-apply-1",
            source_result_id="synced-apply-1",
            source_url="https://jobs.example.test/synced-civic/applied-ai",
            apply_url="https://jobs.example.test/synced-civic/apply",
            canonical_url="https://jobs.example.test/synced-civic/applied-ai",
            is_active=True,
            application_fields_json=greenhouse_application_fields_fixture() if with_application_fields else None,
            application_requirements_json=greenhouse_application_requirements_fixture() if with_application_fields else None,
            pay_transparency_json={"provider": "greenhouse", "normalizedRanges": [{"currency": "USD", "min": 155000, "max": 185000}]}
            if with_application_fields
            else None,
        )
    )
    saved_job = CandidateSavedJob(
        candidate_profile_id=candidate_profile_id,
        job_listing_id=job_listing.id,
        status="saved",
        fit_summary="Strong synced match.",
    )
    session.add(saved_job)
    session.flush()
    return saved_job


def greenhouse_application_fields_fixture() -> dict[str, object]:
    fields = extract_application_fields_from_greenhouse_payload(greenhouse_application_fields_raw_fixture())
    assert fields is not None
    return fields


def greenhouse_application_requirements_fixture() -> dict[str, object]:
    requirements = summarize_greenhouse_application_requirements(greenhouse_application_fields_fixture())
    assert requirements is not None
    return requirements


def greenhouse_application_fields_raw_fixture() -> dict[str, object]:
    return {
        "ats_board_token": "synced-civic",
        "source_result_id": "synced-apply-1",
        "id": "synced-apply-1",
        "questions": [
            {
                "required": True,
                "label": "Resume",
                "fields": [
                    {"name": "resume", "type": "input_file"},
                    {"name": "resume_text", "type": "textarea"},
                ],
            },
            {
                "required": False,
                "label": "LinkedIn",
                "fields": [{"name": "linkedin_url", "type": "input_text"}],
            },
            {
                "required": True,
                "label": "Why do you want this role?",
                "fields": [{"name": "question_1", "type": "textarea"}],
            },
        ],
        "location_questions": [
            {
                "required": True,
                "label": "Location",
                "fields": [{"name": "location", "type": "input_text"}],
            }
        ],
    }


def create_auth_session_token(
    engine,
    *,
    username: str = "rebekah-love",
    email: str = "rebekah-love@jobops.local",
    display_name: str = "Rebekah Love",
    password: str = "rebekah alpha password",
) -> str:
    with Session(engine) as session:
        seed_initial_user(
            session,
            email=email,
            username=username,
            display_name=display_name,
            password=password,
            password_reset_required=False,
        )
        _, raw_token = create_session_for_username(session, username=username, password=password)
        session.commit()
        return raw_token
