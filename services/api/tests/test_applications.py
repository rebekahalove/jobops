from __future__ import annotations

from collections.abc import Iterator
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from jobops_api.auth import SESSION_COOKIE_NAME, create_session_for_username, seed_initial_user
from jobops_api.db.models import Application, ApplicationEvent, Base, CandidateProfile, CandidateSavedJob, JobPosting
from jobops_api.db.seed_profile import seed_public_profile
from jobops_api.db.session import get_db_session
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
        job_id = saved_job.job_id
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
        assert created["status"] == "in_progress"
        assert created["job_id"] == job_id
        assert created["saved_job_id"] == saved_job_id
        assert created["company_name"] == "Example Civic"
        assert created["job_title"] == "Applied AI Engineer"
        assert created["job_url"] == "https://jobs.example.test/example-civic/applied-ai"
        assert created["location"] == "Remote US"
        assert created["source"] == "Company careers"
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
            assert len(session.scalars(select(Application).where(Application.job_id == job_id)).all()) == 1
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
) -> CandidateSavedJob:
    job = JobPosting(
        title=title,
        company_name="Example Civic",
        job_url="https://jobs.example.test/example-civic/applied-ai",
        canonical_url="https://jobs.example.test/example-civic/applied-ai",
        apply_url="https://jobs.example.test/example-civic/apply",
        normalized_url=f"https://jobs.example.test/example-civic/{title.lower().replace(' ', '-')}",
        source="Company careers",
        source_provider="greenhouse",
        provenance="provider_result",
        location="Remote US",
        remote_work_mode="remote",
        employment_type="Full-time",
        salary_text="USD 150,000-180,000",
        posting_date=date(2026, 5, 20),
    )
    session.add(job)
    session.flush()
    saved_job = CandidateSavedJob(
        candidate_profile_id=candidate_profile_id,
        job_id=job.id,
        fit_summary="Matches applied AI and platform engineering goals.",
    )
    session.add(saved_job)
    session.flush()
    return saved_job


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
