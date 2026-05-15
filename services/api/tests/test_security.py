from __future__ import annotations

from collections.abc import Iterator

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from jobops_api.db.models import Base
from jobops_api.db.seed_profile import seed_public_profile
from jobops_api.db.session import get_db_session
from jobops_api.main import app, configure_cors
from jobops_api.security import INTERNAL_API_KEY_HEADER


def test_public_health_does_not_require_internal_key() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200


def test_public_profile_read_does_not_require_internal_key() -> None:
    engine = create_seeded_engine()

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        client = TestClient(app)
        response = client.get("/v1/profile-by-hostname/rebekahalove.dev")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["slug"] == "rebekah-love"


def test_protected_endpoint_rejects_missing_internal_key_in_prod(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    client = TestClient(app)

    response = client.post("/v1/profiles/rebekah-love/questions", json={"question": "What has Rebekah built?"})

    assert response.status_code == 401
    assert "test-secret" not in response.text


def test_protected_endpoint_rejects_invalid_internal_key_in_prod(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    client = TestClient(app)

    response = client.post(
        "/v1/profiles/rebekah-love/questions",
        headers={INTERNAL_API_KEY_HEADER: "wrong-secret"},
        json={"question": "What has Rebekah built?"},
    )

    assert response.status_code == 403
    assert "test-secret" not in response.text
    assert "wrong-secret" not in response.text


def test_protected_endpoint_accepts_valid_internal_key_in_prod(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    engine = create_seeded_engine()

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        client = TestClient(app)
        response = client.post(
            "/v1/profiles/rebekah-love/questions",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            json={"question": "What has Rebekah built?"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["verifiedFactsUsed"] == []


def test_protected_endpoint_fails_closed_when_prod_key_is_missing(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "")
    client = TestClient(app)

    response = client.post("/v1/profiles/rebekah-love/questions", json={"question": "What has Rebekah built?"})

    assert response.status_code == 503


def test_cors_allows_configured_origin_and_internal_key_header() -> None:
    cors_app = FastAPI()
    configure_cors(cors_app, allowed_origins=("https://rebekahalove.dev",))

    @cors_app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    client = TestClient(cors_app)
    response = client.options(
        "/health",
        headers={
            "Origin": "https://rebekahalove.dev",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Content-Type, X-JobOps-Internal-Key",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://rebekahalove.dev"
    allowed_headers = response.headers["access-control-allow-headers"].lower()
    assert "content-type" in allowed_headers
    assert "x-jobops-internal-key" in allowed_headers


def create_seeded_engine():
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
            hostname="rebekahalove.dev",
        )
        session.commit()

    return engine
