from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import jobops_api.command_center as command_center_module
from jobops_api.db.models import Base
from jobops_api.db.seed_profile import seed_public_profile
from jobops_api.db.session import get_db_session
from jobops_api.main import app
from jobops_api.settings import Settings


def test_interprets_profile_related_commands_as_profile_intake() -> None:
    assert command_center_module.interpret_command("I want to be an Applied AI Engineer.") == "profile_intake"
    assert command_center_module.interpret_command("Update my profile with this project.") == "profile_intake"
    assert command_center_module.interpret_command("My experience includes Python and LLM evals.") == "profile_intake"
    assert command_center_module.interpret_command("Add it to my jobs list.") == "add_job_from_url"
    assert command_center_module.interpret_command("Tell JobOps this detail.", active_workspace="profile") == "profile_intake"


def test_command_endpoint_executes_profile_intake_in_mock_mode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(command_center_module, "load_settings", lambda: make_settings(tmp_path))
    engine = create_seeded_engine()

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        client = TestClient(app)
        response = client.post(
            "/v1/command-center/commands",
            json={
                "command": "I want to be an Applied AI Engineer.",
                "active_workspace": "profile",
            },
        )
    finally:
        app.dependency_overrides.clear()

    payload = response.json()
    assert response.status_code == 200
    assert payload["assistant_message"]
    assert payload["target_workspace"] == "profile"
    assert payload["actions"][0]["type"] == "profile_intake"
    assert payload["actions"][0]["status"] == "completed"
    assert payload["actions"][0]["targetWorkspace"] == "profile"
    assert payload["result_payload"]["profileDraft"]["targetRoleIntent"]["targetTitles"] == "Applied AI Engineer"


def test_latest_profile_draft_endpoint_returns_saved_snapshot(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(command_center_module, "load_settings", lambda: make_settings(tmp_path))
    engine = create_seeded_engine()

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        client = TestClient(app)
        client.post(
            "/v1/command-center/commands",
            json={"command": "I want to be an Applied AI Engineer."},
        )
        response = client.get("/v1/command-center/profile-draft/rebekah-love")
    finally:
        app.dependency_overrides.clear()

    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["result"]["targetRoleIntent"]["targetTitles"] == "Applied AI Engineer"
    assert "Latest saved intake turn" in payload["result"]["statusSummary"]


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


def make_settings(repo_root: Path) -> Settings:
    return Settings(
        app_env="test",
        cheap_model="mock-cheap",
        database_url=None,
        default_model="mock-default",
        default_candidate_profile_slug="rebekah-love",
        gemini_api_key=None,
        model_provider="mock",
        profile_intake_save_artifacts=False,
        profile_intake_save_raw_text=False,
        repo_root=repo_root,
    )
