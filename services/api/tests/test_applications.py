from __future__ import annotations

from collections.abc import Iterator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from jobops_api.db.models import Base, CandidateProfile
from jobops_api.db.seed_profile import seed_public_profile
from jobops_api.db.session import get_db_session
from jobops_api.main import app


def test_application_tracker_crud_endpoints() -> None:
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

        create_response = client.post(
            "/v1/applications",
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

        list_response = client.get(f"/v1/applications?candidate_profile_id={profile_id}")
        assert list_response.status_code == 200
        applications = list_response.json()
        assert len(applications) == 1
        assert applications[0]["id"] == created["id"]

        status_response = client.patch(
            f"/v1/applications/{created['id']}/status",
            json={"status": "interviewing"},
        )
        assert status_response.status_code == 200
        assert status_response.json()["status"] == "interviewing"

        event_response = client.post(
            f"/v1/applications/{created['id']}/events",
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


def test_application_create_can_resolve_candidate_profile_slug() -> None:
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
        response = client.post(
            "/v1/applications",
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
