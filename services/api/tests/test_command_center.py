from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import jobops_api.command_center as command_center_module
from jobops_api.auth import SESSION_COOKIE_NAME, create_session_for_username, seed_initial_user
from jobops_api.db.models import Base, ProfileIntakeSession, RoleTarget, TargetCompany
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
    assert command_center_module.interpret_command("https://example.com/careers") == "unknown"
    assert command_center_module.interpret_command("Update CivicActions job listings URL to https://example.com") == "company_update"
    assert command_center_module.interpret_command("Find companies in civic tech.") == "company_discovery"
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
        session_token = create_auth_session_token(engine)
        response = client.post(
            "/v1/command-center/commands",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
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
    assert payload["statusUpdates"][0]["stage"] == "router"
    assert payload["statusUpdates"][0]["actionType"] == "profile_intake"
    assert "routed this command to Update profile" in payload["statusUpdates"][0]["message"]
    assert payload["result_payload"]["profileDraft"]["targetRoleIntent"]["targetTitles"] == "Applied AI Engineer"
    assert payload["result_payload"]["modelRequest"]["task"] == "profile_draft_update"
    assert payload["result_payload"]["modelRequest"]["messages"][1]["role"] == "user"
    assert "I want to be an Applied AI Engineer." in payload["result_payload"]["modelRequest"]["messages"][1]["content"]
    assert payload["result_payload"]["modelResponse"]["provider"] == "mock"
    assert '"section": "basics_and_targets"' in payload["result_payload"]["modelResponse"]["text"]


def test_command_endpoint_routes_pasted_resume_to_profile_intake(tmp_path: Path, monkeypatch) -> None:
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
        session_token = create_auth_session_token(engine)
        response = client.post(
            "/v1/command-center/commands",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
            json={
                "command": (
                    "PROFESSIONAL SUMMARY\n"
                    "Applied AI Systems Engineer building production RAG systems.\n\n"
                    "CORE SKILLS\n"
                    "Python, FastAPI, PostgreSQL, LLM evaluation\n\n"
                    "PROFESSIONAL EXPERIENCE\n"
                    "Shadow Network Intelligence - Founder - 2024-Present\n"
                    "Built AI reporting workflows.\n\n"
                    "EDUCATION\n"
                    "B.A., Fine Arts - Indiana University"
                ),
            },
        )
    finally:
        app.dependency_overrides.clear()

    payload = response.json()
    assert response.status_code == 200
    assert payload["actions"][0]["type"] == "profile_intake"
    assert payload["actions"][0]["status"] == "completed"
    assert payload["statusUpdates"][0]["actionType"] == "profile_intake"
    assert "routed this command to Update profile" in payload["statusUpdates"][0]["message"]


def test_command_endpoint_returns_json_profile_intake_failure_when_gemini_times_out(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    monkeypatch.setattr(
        command_center_module,
        "load_settings",
        lambda: Settings(
            app_env="test",
            cheap_model="mock-cheap",
            company_discovery_search_grounding_enabled=True,
            database_url=None,
            default_model="mock-default",
            gemini_api_key="test-key",
            model_provider="gemini",
            profile_intake_save_artifacts=False,
            profile_intake_save_raw_text=False,
            repo_root=tmp_path,
            llm_request_timeout_seconds=2,
        ),
    )

    def raise_timeout(request, timeout):
        raise TimeoutError("read timed out")

    monkeypatch.setattr("urllib.request.urlopen", raise_timeout)
    engine = create_seeded_engine()

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        client = TestClient(app)
        session_token = create_auth_session_token(engine)
        response = client.post(
            "/v1/command-center/commands",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
            json={
                "command": (
                    "PROFESSIONAL SUMMARY\nApplied AI Systems Engineer\n\n"
                    "CORE SKILLS\nPython, FastAPI, LLM evaluation\n\n"
                    "PROFESSIONAL EXPERIENCE\nBuilt RAG workflows.\n\n"
                    "EDUCATION\nB.A., Fine Arts - Indiana University"
                ),
            },
        )
    finally:
        app.dependency_overrides.clear()

    payload = response.json()
    assert response.status_code == 200
    assert payload["actions"][0]["type"] == "profile_intake"
    assert payload["actions"][0]["status"] == "failed"
    assert payload["actions"][0]["targetWorkspace"] == "profile"
    assert payload["actions"][0]["resultPayload"]["code"] == "MODEL_PROVIDER_ERROR"
    assert payload["assistant_message"] == "Profile intake model call failed. No draft data was applied."
    assert payload["statusUpdates"][0]["actionType"] == "profile_intake"


def test_command_stream_emits_router_status_before_result(tmp_path: Path, monkeypatch) -> None:
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
        session_token = create_auth_session_token(engine)
        with client.stream(
            "POST",
            "/v1/command-center/commands/stream",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
            json={
                "command": (
                    "PROFESSIONAL SUMMARY\nApplied AI Systems Engineer\n\n"
                    "CORE SKILLS\nPython, FastAPI, LLM evaluation\n\n"
                    "PROFESSIONAL EXPERIENCE\nBuilt RAG workflows.\n\n"
                    "EDUCATION\nB.A., Fine Arts - Indiana University"
                ),
            },
        ) as response:
            events = [json.loads(line) for line in response.iter_lines() if line]
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert events[0]["type"] == "status"
    assert events[0]["statusUpdate"]["actionType"] == "profile_intake"
    assert "routed this command to Update profile" in events[0]["statusUpdate"]["message"]
    assert events[1]["type"] == "result"
    assert events[1]["result"]["actions"][0]["type"] == "profile_intake"


def test_command_stream_emits_result_for_profile_intake_validation_failure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    monkeypatch.setattr(command_center_module, "load_settings", lambda: make_settings(tmp_path))

    def fake_run_profile_intake_extraction(request, *, db_session, settings, candidate_profile=None):
        return SimpleNamespace(
            status_code=502,
            body={
                "ok": False,
                "error": "Profile intake model response was truncated before valid JSON completed. No draft data was applied.",
                "code": "model_response_truncated",
                "issues": ["Output is not valid JSON.", "Model response appears to have been truncated before valid JSON completed."],
            },
        )

    monkeypatch.setattr(command_center_module, "run_profile_intake_extraction", fake_run_profile_intake_extraction)
    engine = create_seeded_engine()

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        client = TestClient(app)
        session_token = create_auth_session_token(engine)
        with client.stream(
            "POST",
            "/v1/command-center/commands/stream",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
            json={
                "command": (
                    "PROFESSIONAL SUMMARY\nApplied AI Systems Engineer\n\n"
                    "CORE SKILLS\nPython, FastAPI, LLM evaluation\n\n"
                    "PROFESSIONAL EXPERIENCE\nBuilt RAG workflows.\n\n"
                    "EDUCATION\nB.A., Fine Arts - Indiana University"
                ),
            },
        ) as response:
            events = [json.loads(line) for line in response.iter_lines() if line]
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert events[-1]["type"] == "result"
    result = events[-1]["result"]
    assert result["actions"][0]["type"] == "profile_intake"
    assert result["actions"][0]["status"] == "failed"
    assert result["actions"][0]["resultPayload"]["code"] == "model_response_truncated"
    assert result["assistant_message"] == (
        "Profile intake model response was truncated before valid JSON completed. No draft data was applied."
    )


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

    def fake_run_profile_intake_extraction(request, *, db_session, settings, candidate_profile=None):
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
    assert response.status_updates[0].action_type == "profile_intake"
    assert response.status_updates[0].confidence == "high"
    assert "Update profile" in response.status_updates[0].message
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


def test_command_center_routes_company_url_update_to_company_update(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(command_center_module, "load_settings", lambda: make_settings(tmp_path))
    engine = create_seeded_engine()

    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        company = TargetCompany(
            candidate_profile_id=profile.id,
            name="CivicActions",
            normalized_name="civicactions",
            derivation_status="model_derived",
            review_status="new",
        )
        session.add(company)
        session.commit()
        company_id = company.id

        response = command_center_module.execute_command_center_command(
            command_center_module.CommandCenterCommandRequest(
                command="Update CivicActions job listings URL to https://civicactions.com/careers",
                active_workspace="companies",
            ),
            session=session,
        )

    with Session(engine) as session:
        saved = session.get(TargetCompany, company_id)
        assert response.actions[0].type == "company_update"
        assert response.actions[0].status == "completed"
        assert response.target_workspace == "companies"
        assert response.result_payload is not None
        assert response.result_payload["routerDecision"]["actionType"] == "company_update"
        assert response.result_payload["routerModelRequest"]["task"] == "command_router"
        assert response.result_payload["routerModelRequest"]["searchGrounding"] is False
        assert saved is not None
        assert saved.job_listings_url == "https://civicactions.com/careers"


def test_command_with_url_is_not_automatically_add_job_from_url(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(command_center_module, "load_settings", lambda: make_settings(tmp_path))
    engine = create_seeded_engine()

    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        session.add(
            TargetCompany(
                candidate_profile_id=profile.id,
                name="Higher Ground Labs",
                normalized_name="higher ground labs",
                derivation_status="model_derived",
                review_status="new",
            )
        )
        session.commit()
        response = command_center_module.execute_command_center_command(
            command_center_module.CommandCenterCommandRequest(
                command="Set the careers URL for Higher Ground Labs to https://highergroundlabs.com/jobs",
                active_workspace="companies",
            ),
            session=session,
        )

    assert response.actions[0].type == "company_update"
    assert response.actions[0].status == "completed"


def test_command_center_routes_generic_company_url_update_to_company_update(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(command_center_module, "load_settings", lambda: make_settings(tmp_path))
    engine = create_seeded_engine()

    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        company = TargetCompany(
            candidate_profile_id=profile.id,
            name="CivicActions",
            normalized_name="civicactions",
            derivation_status="model_derived",
            review_status="new",
        )
        session.add(company)
        session.commit()
        company_id = company.id

        response = command_center_module.execute_command_center_command(
            command_center_module.CommandCenterCommandRequest(
                command="Update the URL for CivicActions to https://civicactions.com",
                active_workspace="companies",
            ),
            session=session,
        )

    with Session(engine) as session:
        saved = session.get(TargetCompany, company_id)
        assert response.actions[0].type == "company_update"
        assert response.actions[0].status == "completed"
        assert saved is not None
        assert saved.website_url == "https://civicactions.com"


def test_command_center_add_job_url_remains_planned_tool(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(command_center_module, "load_settings", lambda: make_settings(tmp_path))
    engine = create_seeded_engine()

    with Session(engine) as session:
        response = command_center_module.execute_command_center_command(
            command_center_module.CommandCenterCommandRequest(command="Add this job: https://company.com/jobs/123"),
            session=session,
        )

    assert response.actions[0].type == "add_job_from_url"
    assert response.actions[0].status == "planned"


def test_router_unavailable_ambiguous_url_asks_for_clarification(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(command_center_module, "load_settings", lambda: make_settings(tmp_path))
    engine = create_seeded_engine()

    monkeypatch.setattr(
        command_center_module,
        "run_command_router",
        lambda *args, **kwargs: SimpleNamespace(
            decision=None,
            body={"ok": False, "error": "router unavailable"},
            status_code=503,
            unavailable=True,
        ),
    )

    with Session(engine) as session:
        response = command_center_module.execute_command_center_command(
            command_center_module.CommandCenterCommandRequest(command="https://example.com/careers"),
            session=session,
        )

    assert response.actions[0].type == "unknown"
    assert response.actions[0].status == "needs_confirmation"
    assert "save this as a job posting" in response.assistant_message


def test_router_unavailable_uses_conservative_fallback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(command_center_module, "load_settings", lambda: make_settings(tmp_path))
    engine = create_seeded_engine()

    monkeypatch.setattr(
        command_center_module,
        "run_command_router",
        lambda *args, **kwargs: SimpleNamespace(
            decision=None,
            body={"ok": False, "error": "router unavailable"},
            status_code=503,
            unavailable=True,
        ),
    )

    with Session(engine) as session:
        response = command_center_module.execute_command_center_command(
            command_center_module.CommandCenterCommandRequest(
                command="Update CivicActions job listings URL to https://civicactions.com/careers",
                active_workspace="companies",
            ),
            session=session,
        )

    assert response.actions[0].type == "company_update"
    assert response.actions[0].status == "needs_confirmation"
    assert "router was unavailable" in response.actions[0].summary
    assert response.target_workspace == "companies"


def test_router_unavailable_still_executes_profile_intake_fallback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(command_center_module, "load_settings", lambda: Settings(
        app_env="test",
        cheap_model="mock-cheap",
        company_discovery_search_grounding_enabled=True,
        database_url=None,
        default_model="mock-default",
        gemini_api_key="test-key",
        model_provider="gemini",
        profile_intake_save_artifacts=False,
        profile_intake_save_raw_text=False,
        repo_root=tmp_path,
    ))
    engine = create_seeded_engine()

    monkeypatch.setattr(
        command_center_module,
        "run_command_router",
        lambda *args, **kwargs: SimpleNamespace(
            decision=None,
            body={"ok": False, "error": "router unavailable"},
            status_code=503,
            unavailable=True,
        ),
    )

    def fake_run_profile_intake_extraction(request, *, db_session, settings, candidate_profile=None):
        return SimpleNamespace(
            status_code=200,
            body={
                "ok": True,
                "result": {
                    "assistantMessage": "I updated your profile draft from the pasted resume text.",
                    "targetRoleIntent": {},
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
                command="Resume\nExperience\nApplied AI Engineer\nBuilt model evaluation workflows.",
                active_workspace="profile",
            ),
            session=session,
        )

    assert response.actions[0].type == "profile_intake"
    assert response.actions[0].status == "completed"
    assert response.target_workspace == "profile"
    assert "updated your profile draft" in response.assistant_message


def test_executable_command_without_candidate_slug_or_default_fails_clearly(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(command_center_module, "load_settings", lambda: make_settings(tmp_path))
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        response = command_center_module.execute_command_center_command(
            command_center_module.CommandCenterCommandRequest(command="I want to be an Applied AI Engineer."),
            session=session,
        )

    assert response.actions[0].type == "profile_intake"
    assert response.actions[0].status == "failed"
    assert response.result_payload == {
        "ok": False,
        "error": (
            "Candidate profile slug is required when no authenticated candidate profile is available."
        ),
        "code": "candidate_profile_slug_required",
    }


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
        session_token = create_auth_session_token(engine)
        client.post(
            "/v1/command-center/commands",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
            json={"command": "I want to be an Applied AI Engineer."},
        )
        response = client.get(
            "/v1/command-center/profile-draft/rebekah-love",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
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
        _, raw_token = create_session_for_username(session, username="rebekah-love", password="rebekah alpha password")
        session.commit()
        return raw_token


def make_settings(repo_root: Path) -> Settings:
    return Settings(
        app_env="test",
        cheap_model="mock-cheap",
        company_discovery_search_grounding_enabled=True,
        database_url=None,
        default_model="mock-default",
        gemini_api_key=None,
        model_provider="mock",
        profile_intake_save_artifacts=False,
        profile_intake_save_raw_text=False,
        repo_root=repo_root,
    )
