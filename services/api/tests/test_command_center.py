from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import jobops_api.command_center as command_center_module
from jobops_api.db.models import Base, ProfileIntakeSession, RoleTarget
from jobops_api.db.seed_profile import seed_public_profile
from jobops_api.db.session import get_db_session
from jobops_api.main import app
from jobops_api.security import INTERNAL_API_KEY_HEADER
from jobops_api.settings import Settings


def test_interprets_profile_related_commands_as_profile_intake() -> None:
    assert command_center_module.interpret_command("I want to be an Applied AI Engineer.") == "profile_intake"
    assert command_center_module.interpret_command("Update my profile with this project.") == "profile_intake"
    assert command_center_module.interpret_command("My experience includes Python and LLM evals.") == "profile_intake"
    assert command_center_module.interpret_command("Add it to my jobs list.") == "add_job_from_url"
    assert command_center_module.interpret_command("Tell JobOps this detail.", active_workspace="profile") == "profile_intake"


def test_command_endpoint_executes_profile_intake_in_mock_mode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
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
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
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
    assert payload["result_payload"]["modelRequest"]["task"] == "profile_draft_update"
    assert payload["result_payload"]["modelRequest"]["messages"][1]["role"] == "user"
    assert "I want to be an Applied AI Engineer." in payload["result_payload"]["modelRequest"]["messages"][1]["content"]
    assert payload["result_payload"]["modelResponse"]["provider"] == "mock"
    assert "assistantMessage" in payload["result_payload"]["modelResponse"]["text"]


def test_profile_intake_command_passes_current_saved_draft_as_existing_draft(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(command_center_module, "load_settings", lambda: make_settings(tmp_path))
    engine = create_seeded_engine()
    captured = {}

    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        intake_session = ProfileIntakeSession(candidate_profile_id=profile.id, status="active", redacted_state={})
        session.add(intake_session)
        session.flush()
        session.add(
            RoleTarget(
                candidate_profile_id=profile.id,
                profile_intake_session_id=intake_session.id,
                target_titles=["Applied AI Engineer"],
                role_families=["Applied AI"],
                preferred_locations=["Louisville, KY"],
                work_modes=["flexible"],
                constraints={"domainsOrIndustries": "developer tools"},
                source="model",
                review_status="needs_review",
                visibility="private",
                publication_status="not_published",
                is_active=True,
            )
        )
        session.commit()

    def fake_run_profile_intake_extraction(request, *, db_session, settings):
        captured["request"] = request
        return SimpleNamespace(
            status_code=200,
            body={
                "ok": True,
                "modelRequest": {
                    "task": "profile_draft_update",
                    "messages": [
                        {"role": "system", "content": "system prompt"},
                        {"role": "user", "content": "current draft with Louisville, KY"},
                    ],
                },
                "modelResponse": {
                    "provider": "test",
                    "text": "{\"assistantMessage\":\"Updated.\"}",
                },
                "result": {
                    "assistantMessage": "Updated.",
                    "targetRoleIntent": request.existing_draft["targetRoleIntent"],
                    "draftFacts": [],
                    "skillClaims": [],
                    "experienceAndProjects": [],
                    "evidenceLinks": [],
                    "clarifyingQuestions": [],
                    "changeSummary": [],
                },
            },
        )

    monkeypatch.setattr(command_center_module, "run_profile_intake_extraction", fake_run_profile_intake_extraction)

    with Session(engine) as session:
        response = command_center_module.execute_command_center_command(
            command_center_module.CommandCenterCommandRequest(
                command="or maybe on location in London, UK as well",
                active_workspace="profile",
            ),
            session=session,
        )

    request = captured["request"]
    assert response.actions[0].status == "completed"
    assert request.latest_user_message == "or maybe on location in London, UK as well"
    assert request.candidate_profile_slug == "rebekah-love"
    assert request.existing_draft["targetRoleIntent"]["targetTitles"] == "Applied AI Engineer"
    assert request.existing_draft["targetRoleIntent"]["preferredLocations"] == "Louisville, KY"
    assert response.result_payload is not None
    assert response.result_payload["modelRequest"]["messages"][1]["content"] == "current draft with Louisville, KY"
    assert response.result_payload["modelResponse"]["text"] == "{\"assistantMessage\":\"Updated.\"}"


def test_profile_intake_command_missing_candidate_profile_returns_clear_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(command_center_module, "load_settings", lambda: make_settings(tmp_path))
    engine = create_seeded_engine()

    def fail_if_called(*args, **kwargs):
        raise AssertionError("profile intake should not run for a missing candidate profile")

    monkeypatch.setattr(command_center_module, "run_profile_intake_extraction", fail_if_called)

    with Session(engine) as session:
        response = command_center_module.execute_command_center_command(
            command_center_module.CommandCenterCommandRequest(
                command="I want to be an Applied AI Engineer.",
                candidate_profile_slug="missing-profile",
            ),
            session=session,
        )

    assert response.assistant_message == "Candidate profile not found."
    assert response.actions[0].type == "profile_intake"
    assert response.actions[0].status == "failed"
    assert response.result_payload == {
        "ok": False,
        "error": "Candidate profile not found.",
        "code": "candidate_profile_not_found",
    }


def test_non_profile_command_returns_planned_action_without_profile_intake(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(command_center_module, "load_settings", lambda: make_settings(tmp_path))
    engine = create_seeded_engine()

    def fail_if_called(*args, **kwargs):
        raise AssertionError("profile intake should not run for planned non-profile commands")

    monkeypatch.setattr(command_center_module, "run_profile_intake_extraction", fail_if_called)

    with Session(engine) as session:
        response = command_center_module.execute_command_center_command(
            command_center_module.CommandCenterCommandRequest(command="Prioritize my saved jobs for today."),
            session=session,
        )

    assert response.actions[0].type == "prioritize_jobs"
    assert response.actions[0].status == "planned"
    assert response.target_workspace == "jobs"


def test_latest_profile_draft_endpoint_returns_saved_snapshot(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
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
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            json={"command": "I want to be an Applied AI Engineer."},
        )
        response = client.get(
            "/v1/command-center/profile-draft/rebekah-love",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
        )
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
        company_discovery_search_grounding_enabled=True,
        database_url=None,
        default_model="mock-default",
        default_candidate_profile_slug="rebekah-love",
        gemini_api_key=None,
        model_provider="mock",
        profile_intake_save_artifacts=False,
        profile_intake_save_raw_text=False,
        repo_root=repo_root,
    )
