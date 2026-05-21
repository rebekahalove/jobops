from __future__ import annotations

from collections.abc import Iterator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from jobops_api.auth import seed_initial_user
from jobops_api.db.models import (
    AlphaAccessRequest,
    Application,
    Base,
    CandidateProfile,
    CommandInteractionLog,
    JobRole,
    ProfileFact,
    ProfileFactDraft,
    TargetCompany,
    Tenant,
    User,
)
from jobops_api.db.session import get_db_session
from jobops_api.main import app
from jobops_api.security import INTERNAL_API_KEY_HEADER


INTERNAL_HEADERS = {INTERNAL_API_KEY_HEADER: "test-secret"}


def test_public_metrics_return_safe_aggregate_counts(monkeypatch) -> None:
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    seed_metrics_records(engine)

    with app_with_session(engine):
        response = TestClient(app).get("/v1/public/jobops/metrics", headers=INTERNAL_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    metrics = {item["id"]: item["value"] for item in payload["result"]["metrics"]}
    assert metrics == {
        "alphaAccessRequests": 1,
        "usersOnboarded": 1,
        "companiesTracked": 1,
        "jobsTracked": 1,
        "profileDraftsCreated": 1,
        "profileDraftsPublished": 1,
        "applicationsTracked": 1,
        "aiAssistedActionsCompleted": 1,
    }
    assert "Private Co" not in str(payload)
    assert "private note" not in str(payload)


def test_alpha_access_request_submission_stores_request(monkeypatch) -> None:
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    with app_with_session(engine):
        response = TestClient(app).post(
            "/v1/public/jobops/access-requests",
            headers=INTERNAL_HEADERS,
            json={
                "name": "  Chance   Alpha ",
                "email": "CHANCE@example.com",
                "note": "Interested in human-in-the-loop job search workflows.",
            },
        )

    assert response.status_code == 201
    assert (
        response.json()["result"]["message"]
        == "Thanks. Your alpha access request was received. I'll review requests as the product becomes ready for additional users."
    )
    with Session(engine) as session:
        stored = session.scalar(select(AlphaAccessRequest))
        assert stored is not None
        assert stored.name == "Chance Alpha"
        assert stored.email == "chance@example.com"
        assert stored.note == "Interested in human-in-the-loop job search workflows."


def test_alpha_access_request_rejects_invalid_email(monkeypatch) -> None:
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    with app_with_session(engine):
        response = TestClient(app).post(
            "/v1/public/jobops/access-requests",
            headers=INTERNAL_HEADERS,
            json={"name": "Chance Alpha", "email": "not-an-email"},
        )

    assert response.status_code == 422


def seed_metrics_records(engine) -> None:
    with Session(engine) as session:
        auth = seed_initial_user(
            session,
            email="chance@example.com",
            username="chance-alpha",
            display_name="Chance Alpha",
            password="chance alpha password",
            password_reset_required=False,
        )
        request = AlphaAccessRequest(name="Alpha One", email="alpha@example.com", note="private note")
        company = TargetCompany(candidate_profile_id=auth.candidate_profile.id, name="Private Co")
        job = JobRole(candidate_profile_id=auth.candidate_profile.id, target_company=company, title="Private Role")
        application = Application(
            candidate_profile_id=auth.candidate_profile.id,
            target_company=company,
            job_role=job,
            company_name="Private Co",
            job_title="Private Role",
            notes="private note",
        )
        draft = ProfileFactDraft(
            candidate_profile_id=auth.candidate_profile.id,
            claim="Private draft fact",
            fact_type="experience",
            source="model",
        )
        published_fact = ProfileFact(
            candidate_profile_id=auth.candidate_profile.id,
            fact_type="project",
            claim="Public fact",
            source="human",
            visibility="public",
            verification_status="published",
        )
        action = CommandInteractionLog(
            user_id=auth.user.id,
            tenant_id=auth.tenant.id,
            candidate_profile_id=auth.candidate_profile.id,
            user_message="private command",
            action_applied=True,
            final_response="private response",
        )
        session.add_all([request, company, job, application, draft, published_fact, action])
        session.commit()


class app_with_session:
    def __init__(self, engine) -> None:
        self.engine = engine

    def __enter__(self):
        def override_session() -> Iterator[Session]:
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[get_db_session] = override_session
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        app.dependency_overrides.clear()
