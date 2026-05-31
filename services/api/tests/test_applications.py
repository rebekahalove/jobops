from __future__ import annotations

from collections.abc import Iterator
from datetime import date

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
    JobPageExtraction,
    JobPosting,
)
from jobops_api.db.seed_profile import seed_public_profile
from jobops_api.db.session import get_db_session
from jobops_api.job_page_extraction import FetchResult
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
        extraction = JobPageExtraction(
            job_id=saved_job.job_id,
            source_url="https://jobs.example.test/example-civic/apply",
            final_url="https://jobs.example.test/example-civic/apply",
            platform="generic",
            extraction_status="succeeded",
            required_materials=[{"type": "resume", "label": "Resume", "required": True, "evidence": "Resume required"}],
            optional_materials=[{"type": "cover_letter", "label": "Cover Letter", "required": False, "evidence": "Optional cover letter"}],
            application_fields=[
                {
                    "fieldType": "textarea",
                    "label": "Why are you interested?",
                    "required": True,
                    "normalizedKey": "why_interested",
                    "minLength": None,
                    "maxLength": 500,
                    "limitSource": "html_attribute",
                    "options": [],
                    "acceptedFileTypes": [],
                    "multiple": False,
                    "evidence": "Why are you interested?",
                }
            ],
            screening_questions=[],
            detected_requirements={"resumeRequired": True, "coverLetterOptional": True},
            extraction_summary="Detected application requirements.",
            confidence="high",
            warnings=[],
        )
        session.add(extraction)
        session.flush()
        extraction_id = extraction.id
        application = Application(
            candidate_profile_id=profile.id,
            job_id=saved_job.job_id,
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
        assert payload["contextManifest"]["jobDescriptionSource"] == "full_stored"

        with Session(engine) as session:
            bundle = session.scalar(select(ApplicationMaterialBundle).where(ApplicationMaterialBundle.application_id == application_id))
            assert bundle is not None
            assert bundle.model_provider == "mock"
            assert bundle.source_context_snapshot["manifest"]["jobDescriptionSource"] == "full_stored"
            assert bundle.source_context_snapshot["manifest"]["jobPageExtractionId"] == extraction_id
            assert bundle.source_context_snapshot["context"]["jobPageExtraction"]["requiredMaterials"][0]["type"] == "resume"
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


def test_extract_application_requirements_creates_global_job_extraction(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    monkeypatch.setenv("JOBOPS_LLM_PROVIDER", "mock")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    html = """
    <html><head><title>Applied AI Engineer</title></head><body>
      <script type="application/json">{"fields":{"portfolio_url":{"minLength":10,"maxLength":200}}}</script>
      <form>
        <label for="resume">Resume</label><input id="resume" name="resume" type="file" accept=".pdf,.docx" required>
        <label for="cover">Cover Letter</label><input id="cover" name="cover_letter" type="file">
        <label for="linkedin">LinkedIn Profile</label><input id="linkedin" name="linkedin_url" type="url">
        <label for="github">GitHub</label><input id="github" name="github_url" type="url">
        <label for="portfolio">Portfolio Website</label><input id="portfolio" name="portfolio_url" type="url">
        <label for="salary">Salary expectations</label><input id="salary" name="salary" type="text" maxlength="120">
        <label for="auth">Are you authorized to work in the United States?</label>
        <select id="auth" name="work_auth" required><option>Yes</option><option>No</option></select>
        <label for="why">Why this role?</label><textarea id="why" name="why" minlength="20" maxlength="500" required></textarea>
      </form>
    </body></html>
    """
    monkeypatch.setattr(
        "jobops_api.job_page_extraction.fetch_job_page",
        lambda url: FetchResult(source_url=url, final_url=url, http_status=200, content_type="text/html", text=html),
    )

    session_token = create_auth_session_token(engine)
    with Session(engine) as session:
        profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "rebekah-love"))
        assert profile is not None
        saved_job = create_saved_job(session, candidate_profile_id=profile.id)
        application = Application(
            candidate_profile_id=profile.id,
            job_id=saved_job.job_id,
            saved_job_id=saved_job.id,
            company_name="Example Civic",
            job_title="Applied AI Engineer",
            job_url="https://jobs.example.test/example-civic/applied-ai",
            status="in_progress",
            notes="",
        )
        session.add(application)
        session.commit()
        application_id = application.id
        job_id = saved_job.job_id

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        client = TestClient(app)
        response = client.post(
            f"/v1/applications/{application_id}/requirements/extract",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        assert response.status_code == 201
        payload = response.json()
        assert payload["job_id"] == job_id
        assert payload["extraction_status"] == "succeeded"
        assert payload["platform"] == "generic"
        assert payload["required_materials"][0]["type"] == "resume"
        assert any(field["normalizedKey"] == "linkedin_url" for field in payload["application_fields"])
        assert any(field["normalizedKey"] == "github_url" for field in payload["application_fields"])
        salary_field = next(field for field in payload["application_fields"] if field["normalizedKey"] == "salary_expectation")
        assert salary_field["maxLength"] == 120
        assert salary_field["limitSource"] == "html_attribute"
        portfolio_field = next(field for field in payload["application_fields"] if field["normalizedKey"] == "portfolio_url")
        assert portfolio_field["minLength"] == 10
        assert portfolio_field["maxLength"] == 200
        assert portfolio_field["limitSource"] == "embedded_json"
        assert any(question["category"] == "work_authorization" and question["options"] == ["Yes", "No"] for question in payload["screening_questions"])

        with Session(engine) as session:
            extraction = session.scalar(select(JobPageExtraction).where(JobPageExtraction.job_id == job_id))
            assert extraction is not None
            assert extraction.required_materials[0]["type"] == "resume"
            assert extraction.raw_text_excerpt is not None
            assert extraction.raw_text_excerpt != html

        listed = client.get(
            "/v1/applications",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        assert listed.status_code == 200
        assert listed.json()[0]["latest_job_page_extraction"]["id"] == payload["id"]
    finally:
        app.dependency_overrides.clear()


def test_extract_application_requirements_follows_public_apply_links(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    monkeypatch.setenv("JOBOPS_LLM_PROVIDER", "mock")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    pages = {
        "https://adzuna.example.test/job/123/apply": """
        <html><body><a class="apply-now" href="/redirect/123">Apply now</a></body></html>
        """,
        "https://adzuna.example.test/redirect/123": """
        <html><body><a rel="nofollow" href="https://ats.example.test/apply/abc">Continue to apply</a></body></html>
        """,
        "https://ats.example.test/apply/abc": """
        <html><body><form>
          <label for="resume">Resume</label><input id="resume" name="resume" type="file" required accept=".pdf">
          <label for="auth">Are you authorized to work in the United States?</label>
          <select id="auth" name="work_auth" required><option>Yes</option><option>No</option></select>
        </form></body></html>
        """,
    }

    def fake_fetch(url: str) -> FetchResult:
        text = pages[url]
        return FetchResult(source_url=url, final_url=url, http_status=200, content_type="text/html", text=text)

    monkeypatch.setattr("jobops_api.job_page_extraction.fetch_job_page", fake_fetch)

    session_token = create_auth_session_token(engine)
    with Session(engine) as session:
        profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "rebekah-love"))
        assert profile is not None
        saved_job = create_saved_job(session, candidate_profile_id=profile.id)
        job = session.get(JobPosting, saved_job.job_id)
        assert job is not None
        job.apply_url = "https://adzuna.example.test/job/123/apply"
        application = Application(
            candidate_profile_id=profile.id,
            job_id=saved_job.job_id,
            saved_job_id=saved_job.id,
            company_name="Example Civic",
            job_title="Applied AI Engineer",
            job_url=job.job_url,
            status="in_progress",
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
            f"/v1/applications/{application_id}/requirements/extract",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        assert response.status_code == 201
        payload = response.json()
        assert payload["extraction_status"] == "succeeded"
        assert payload["final_url"] == "https://ats.example.test/apply/abc"
        assert payload["required_materials"][0]["type"] == "resume"
        assert any(question["category"] == "work_authorization" for question in payload["screening_questions"])
        assert any("Followed public apply link" in warning for warning in payload["warnings"])
    finally:
        app.dependency_overrides.clear()


def test_extract_application_requirements_falls_back_from_blocked_apply_url_to_job_url(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    monkeypatch.setenv("JOBOPS_LLM_PROVIDER", "mock")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    def fake_fetch(url: str) -> FetchResult:
        if url == "https://blocked.example.test/apply":
            return FetchResult(source_url=url, final_url=url, http_status=403, content_type="text/html", text="<html>blocked</html>")
        if url == "https://jobs.example.test/example-civic/applied-ai":
            return FetchResult(
                source_url=url,
                final_url=url,
                http_status=200,
                content_type="text/html",
                text='<html><body><a href="https://ats.example.test/apply/abc">Apply for this job</a></body></html>',
            )
        return FetchResult(
            source_url=url,
            final_url=url,
            http_status=200,
            content_type="text/html",
            text='<html><body><form><label for="resume">Resume</label><input id="resume" name="resume" type="file" required></form></body></html>',
        )

    monkeypatch.setattr("jobops_api.job_page_extraction.fetch_job_page", fake_fetch)

    session_token = create_auth_session_token(engine)
    with Session(engine) as session:
        profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "rebekah-love"))
        assert profile is not None
        saved_job = create_saved_job(session, candidate_profile_id=profile.id)
        job = session.get(JobPosting, saved_job.job_id)
        assert job is not None
        job.apply_url = "https://blocked.example.test/apply"
        application = Application(
            candidate_profile_id=profile.id,
            job_id=saved_job.job_id,
            saved_job_id=saved_job.id,
            company_name="Example Civic",
            job_title="Applied AI Engineer",
            job_url=job.job_url,
            status="in_progress",
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
            f"/v1/applications/{application_id}/requirements/extract",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        assert response.status_code == 201
        payload = response.json()
        assert payload["extraction_status"] == "succeeded"
        assert payload["source_url"] == "https://jobs.example.test/example-civic/applied-ai"
        assert payload["final_url"] == "https://ats.example.test/apply/abc"
        assert payload["required_materials"][0]["type"] == "resume"
    finally:
        app.dependency_overrides.clear()


def test_extract_application_requirements_is_private_to_application_owner(monkeypatch) -> None:
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
        saved_job = create_saved_job(session, candidate_profile_id=other_profile.id, title="Private Role")
        application = Application(
            candidate_profile_id=other_profile.id,
            job_id=saved_job.job_id,
            saved_job_id=saved_job.id,
            company_name="Private Co",
            job_title="Private Role",
            status="in_progress",
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
            f"/v1/applications/{application_id}/requirements/extract",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: rebekah_token},
        )
        assert response.status_code == 404
        with Session(engine) as session:
            assert session.scalar(select(JobPageExtraction)) is None
    finally:
        app.dependency_overrides.clear()


def test_second_user_application_reuses_global_job_extraction(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    create_auth_session_token(engine)
    other_token = create_auth_session_token(
        engine,
        username="other-user",
        email="other-user@jobops.local",
        display_name="Other User",
        password="other user alpha password",
    )
    with Session(engine) as session:
        rebekah = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "rebekah-love"))
        other = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "other-user"))
        assert rebekah is not None and other is not None
        saved_job = create_saved_job(session, candidate_profile_id=rebekah.id)
        session.add(CandidateSavedJob(candidate_profile_id=other.id, job_id=saved_job.job_id, fit_summary="Also relevant."))
        session.add_all(
            [
                Application(
                    candidate_profile_id=rebekah.id,
                    job_id=saved_job.job_id,
                    saved_job_id=saved_job.id,
                    company_name="Example Civic",
                    job_title="Applied AI Engineer",
                    status="in_progress",
                ),
                Application(
                    candidate_profile_id=other.id,
                    job_id=saved_job.job_id,
                    company_name="Example Civic",
                    job_title="Applied AI Engineer",
                    status="in_progress",
                ),
                JobPageExtraction(
                    job_id=saved_job.job_id,
                    source_url="https://jobs.example.test/example-civic/apply",
                    platform="generic",
                    extraction_status="succeeded",
                    required_materials=[{"type": "resume", "label": "Resume", "required": True, "evidence": "Resume"}],
                    optional_materials=[],
                    application_fields=[],
                    screening_questions=[],
                    detected_requirements={"resumeRequired": True},
                    confidence="medium",
                    warnings=[],
                ),
            ]
        )
        session.commit()

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        client = TestClient(app)
        response = client.get(
            "/v1/applications",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: other_token},
        )
        assert response.status_code == 200
        listed = response.json()
        assert len(listed) == 1
        assert listed[0]["latest_job_page_extraction"]["detected_requirements"]["resumeRequired"] is True
        assert "notes" in listed[0]
    finally:
        app.dependency_overrides.clear()


def test_extract_application_requirements_persists_fetch_failure(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    monkeypatch.setenv("JOBOPS_LLM_PROVIDER", "mock")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    monkeypatch.setattr(
        "jobops_api.job_page_extraction.fetch_job_page",
        lambda url: FetchResult(source_url=url, final_url=None, http_status=None, content_type=None, text=None, error_message="DNS failed"),
    )

    session_token = create_auth_session_token(engine)
    with Session(engine) as session:
        profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == "rebekah-love"))
        assert profile is not None
        saved_job = create_saved_job(session, candidate_profile_id=profile.id)
        application = Application(
            candidate_profile_id=profile.id,
            job_id=saved_job.job_id,
            saved_job_id=saved_job.id,
            company_name="Example Civic",
            job_title="Applied AI Engineer",
            status="in_progress",
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
            f"/v1/applications/{application_id}/requirements/extract",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
        )
        assert response.status_code == 201
        payload = response.json()
        assert payload["extraction_status"] == "fetch_failed"
        assert payload["error_message"] == "DNS failed"
        assert any("Fetched step 1" in warning for warning in payload["warnings"])
        assert any("Fetch failed at step 1" in warning for warning in payload["warnings"])
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
            job_id=saved_job.job_id,
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
        assert response.json()["contextManifest"]["jobDescriptionSource"] == "excerpt_fallback"
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
        full_description=full_description,
        description_excerpt=description_excerpt,
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
