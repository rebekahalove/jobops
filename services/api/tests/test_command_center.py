from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import jobops_api.command_center as command_center_module
import jobops_api.job_discovery.candidate_discovery.service as candidate_service_module
import jobops_api.job_discovery.service as job_discovery_service_module
from jobops_api.auth import SESSION_COOKIE_NAME, create_session_for_username, seed_initial_user
from jobops_api.company_canonicalization import ensure_candidate_company_link, upsert_canonical_company
from jobops_api.db.models import (
    Base,
    CandidateCompany,
    CandidateSavedJob,
    ExperienceProjectDraft,
    JobListing,
    JobListingSource,
    JobSearchRun,
    ProfileFactDraft,
    ProfileIntakeSession,
    RoleTarget,
    SkillClaim,
)
from jobops_api.db.seed_profile import seed_public_profile
from jobops_api.db.session import get_db_session
from jobops_api.job_discovery.candidate_discovery.direct_url.providers.greenhouse import GreenhouseDirectJobUrlProvider
from jobops_api.job_discovery.candidate_discovery.direct_url.service import DirectJobUrlDiscoveryService
from jobops_api.model_connector import ModelResponse
from jobops_api.main import app
from jobops_api.security import INTERNAL_API_KEY_HEADER
from jobops_api.settings import Settings
from test_candidate_discovery_direct_url import DIRECT_URL, FakeGreenhouseClient


def test_interprets_profile_related_commands_as_profile_intake() -> None:
    assert command_center_module.interpret_command("I want to be an Applied AI Engineer.") == "profile_intake"
    assert command_center_module.interpret_command("Update my profile with this project.") == "profile_intake"
    assert command_center_module.interpret_command("My experience includes Python and LLM evals.") == "profile_intake"
    assert command_center_module.interpret_command("Add it to my jobs list.") == "add_job_from_url"
    assert command_center_module.interpret_command(f"Add this job to my list {DIRECT_URL}") == "add_job_from_url"
    assert command_center_module.interpret_command("https://example.com/careers") == "unknown"
    assert command_center_module.interpret_command("Update CivicActions job listings URL to https://example.com") == "company_update"
    assert command_center_module.interpret_command("Find companies in civic tech.") == "company_discovery"
    assert command_center_module.interpret_command("Find companies hiring AI engineers.", active_workspace="companies") == "company_discovery"
    assert command_center_module.interpret_command("Find jobs at companies I'm following.", active_workspace="jobs") == "job_discovery"
    assert (
        command_center_module.interpret_command(
            "Are there any companies that I should be following, who hire for roles like this?"
        )
        == "company_discovery"
    )
    assert command_center_module.interpret_command("Tell JobOps this detail.", active_workspace="profile") == "profile_intake"
    assert command_center_module.interpret_command("What should I emphasize for AI platform roles?", active_workspace="profile") == "profile_guidance"


def test_command_center_add_job_from_greenhouse_url_creates_db_backed_saved_job(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(command_center_module, "load_settings", lambda: make_settings(tmp_path))
    monkeypatch.setattr(job_discovery_service_module, "create_model_connector", lambda config: DirectUrlPlannerConnector())

    def direct_service_factory(**kwargs):
        return DirectJobUrlDiscoveryService(
            session=kwargs["session"],
            settings=kwargs["settings"],
            providers=(GreenhouseDirectJobUrlProvider(client=FakeGreenhouseClient()),),
        )

    monkeypatch.setattr(candidate_service_module, "DirectJobUrlDiscoveryService", direct_service_factory)
    engine = create_seeded_engine()

    with Session(engine) as session:
        response = command_center_module.execute_command_center_command(
            command_center_module.CommandCenterCommandRequest(
                command=f"add this job to my list {DIRECT_URL}",
                active_workspace="jobs",
            ),
            session=session,
        )
        saved = session.scalar(select(CandidateSavedJob))
        listing = session.scalar(select(JobListing))
        source = session.scalar(select(JobListingSource))
        legacy_job_id = getattr(saved, "job_id", None) if saved is not None else None

    assert response.actions[0].type == "add_job_from_url"
    assert response.actions[0].status == "completed"
    assert response.target_workspace == "jobs"
    assert saved is not None
    assert listing is not None
    assert source is not None
    assert saved.job_listing_id == listing.id
    assert legacy_job_id is None
    assert source.source_provider == "greenhouse"
    assert response.result_payload is not None
    assert response.result_payload["searchPlan"]["mode"] == "direct_job_url"
    assert response.result_payload["diagnostics"]["directUrlIngestion"]["noBroadSearch"] is True
    assert response.result_payload["diagnostics"]["planner"]["commandRouterAction"] == "add_job_from_url"


def test_command_center_ambiguous_url_does_not_mutate_when_router_asks_clarification(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(command_center_module, "load_settings", lambda: make_settings(tmp_path))
    engine = create_seeded_engine()

    with Session(engine) as session:
        response = command_center_module.execute_command_center_command(
            command_center_module.CommandCenterCommandRequest(
                command="this URL is https://example.com",
                active_workspace="jobs",
            ),
            session=session,
        )
        saved_count = len(list(session.scalars(select(CandidateSavedJob))))
        listing_count = len(list(session.scalars(select(JobListing))))

    assert response.actions[0].type == "unknown"
    assert response.actions[0].status == "needs_confirmation"
    assert saved_count == 0
    assert listing_count == 0


def test_company_following_advice_executes_company_discovery(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(command_center_module, "load_settings", lambda: make_settings(tmp_path))
    engine = create_seeded_engine()

    with Session(engine) as session:
        response = command_center_module.execute_command_center_command(
            command_center_module.CommandCenterCommandRequest(
                command=(
                    "Are there any companies that I should be following, who hire for roles like this? "
                    "I don't want to work for defense contractors or gambling related companies."
                ),
                active_workspace="profile",
            ),
            session=session,
        )
        saved = list(session.scalars(select(CandidateCompany)))

    assert response.actions[0].type == "company_discovery"
    assert response.actions[0].status == "completed"
    assert response.target_workspace == "companies"
    assert response.status_updates[0].action_type == "company_discovery"
    assert "Discover companies" in response.status_updates[0].message
    assert len(saved) >= 1


def test_profile_action_summary_counts_only_active_saved_draft_items() -> None:
    summary = command_center_module.build_profile_action_summary(
        {
            "draftFacts": [
                {"claim": "Active", "status": "needs_review", "published": False},
                {"claim": "Archived", "status": "rejected", "published": False},
            ],
            "skillClaims": [
                {"skill": "Python", "status": "draft", "published": False},
                {"skill": "Archived", "status": "rejected", "published": False},
            ],
            "experienceAndProjects": [
                {"title": "Active", "status": "needs_review", "published": False},
                {"title": "Published", "status": "approved", "published": True},
                {"title": "Archived", "status": "rejected", "published": False},
            ],
        }
    )

    assert summary == "Updated the saved profile draft with 1 fact(s), 1 skill claim(s), and 1 experience/project item(s)."


def test_profile_section_failure_status_update_is_truthful() -> None:
    updates = command_center_module.build_profile_section_failure_status_updates(
        [{"section": "skills", "code": "model_output_invalid", "issues": ["Output is not valid JSON."]}]
    )

    assert len(updates) == 1
    assert "skipped skills" in updates[0].message
    assert "continued with the remaining sections" in updates[0].message


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


def test_job_discovery_stream_returns_async_run_without_inline_provider_search(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    monkeypatch.setattr(command_center_module, "load_settings", lambda: make_settings(tmp_path))
    starts: list[str] = []

    monkeypatch.setattr(
        command_center_module,
        "run_command_router",
        lambda *args, **kwargs: SimpleNamespace(
            decision=command_center_module.CommandRouterOutput(
                actionType="job_discovery",
                confidence="high",
                targetWorkspace="jobs",
            ),
            body={"ok": True},
            status_code=200,
            unavailable=False,
        ),
    )

    def fake_start_job_discovery_run(request, *, db_session, candidate_profile, background_tasks, session_factory=None):
        starts.append(request.latest_user_message)
        return (
            SimpleNamespace(
                id="async-run-1",
                status="queued",
                saved_count=0,
                updated_existing_count=0,
                duplicate_count=0,
                skipped_count=0,
                total_provider_results=0,
                model_selected_count=0,
                provider_error_count=0,
            ),
            True,
        )

    def fail_inline_job_discovery(*args, **kwargs):
        raise AssertionError("job discovery should not run inline in the stream")

    monkeypatch.setattr(command_center_module, "start_job_discovery_run", fake_start_job_discovery_run)
    monkeypatch.setattr(command_center_module, "run_job_discovery", fail_inline_job_discovery)
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
            json={"command": "find some jobs from my companies list", "active_workspace": "jobs"},
        ) as response:
            events = [json.loads(line) for line in response.iter_lines() if line]
    finally:
        app.dependency_overrides.clear()

    result = events[-1]["result"]
    assert response.status_code == 200
    assert starts == ["find some jobs from my companies list"]
    assert result["actions"][0]["type"] == "job_discovery"
    assert result["actions"][0]["status"] == "running"
    assert result["actions"][0]["resultPayload"]["jobSearchRunId"] == "async-run-1"
    assert result["actions"][0]["resultPayload"]["async"] is True


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


def test_non_stream_fallback_reuses_recent_mutating_stream_response(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    monkeypatch.setattr(command_center_module, "load_settings", lambda: make_settings(tmp_path))
    calls: list[str] = []

    monkeypatch.setattr(
        command_center_module,
        "run_command_router",
        lambda *args, **kwargs: SimpleNamespace(
            decision=command_center_module.CommandRouterOutput(
                actionType="job_discovery",
                confidence="high",
                targetWorkspace="jobs",
            ),
            body={"ok": True},
            status_code=200,
            unavailable=False,
        ),
    )

    def fake_start_job_discovery_run(request, *, db_session, candidate_profile, background_tasks, session_factory=None):
        calls.append(request.latest_user_message)
        return (
            SimpleNamespace(
                id="stream-run-1",
                status="queued",
                saved_count=0,
                updated_existing_count=0,
                duplicate_count=0,
                skipped_count=0,
                total_provider_results=0,
                model_selected_count=0,
                provider_error_count=0,
            ),
            True,
        )

    monkeypatch.setattr(command_center_module, "start_job_discovery_run", fake_start_job_discovery_run)
    engine = create_seeded_engine()

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        client = TestClient(app)
        session_token = create_auth_session_token(engine)
        command_payload = {
            "command": "find some jobs from my companies list",
            "active_workspace": "jobs",
        }
        with client.stream(
            "POST",
            "/v1/command-center/commands/stream",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
            json=command_payload,
        ) as stream_response:
            events = [json.loads(line) for line in stream_response.iter_lines() if line]
        fallback_response = client.post(
            "/v1/command-center/commands",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
            json=command_payload,
        )
    finally:
        app.dependency_overrides.clear()

    fallback_payload = fallback_response.json()
    assert stream_response.status_code == 200
    assert fallback_response.status_code == 200
    assert events[-1]["result"]["actions"][0]["resultPayload"]["jobSearchRunId"] == "stream-run-1"
    assert fallback_payload["actions"][0]["resultPayload"]["jobSearchRunId"] == "stream-run-1"
    assert calls == ["find some jobs from my companies list"]


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


def test_profile_guidance_command_does_not_run_profile_intake(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(command_center_module, "load_settings", lambda: make_settings(tmp_path))
    engine = create_seeded_engine()

    def fail_if_called(*args, **kwargs):
        raise AssertionError("profile intake should not run for guidance-only profile commands")

    monkeypatch.setattr(command_center_module, "run_profile_intake_extraction", fail_if_called)

    with Session(engine) as session:
        response = command_center_module.execute_command_center_command(
            command_center_module.CommandCenterCommandRequest(
                command="What should I emphasize for applied AI roles?",
                active_workspace="profile",
            ),
            session=session,
        )

    assert response.actions[0].type == "profile_guidance"
    assert response.actions[0].summary == "Read-only guidance completed. No profile data was changed."
    assert response.result_payload is not None
    assert response.result_payload["mutated"] is False


def test_profile_guidance_command_uses_model_backed_read_only_workflow(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(command_center_module, "load_settings", lambda: make_settings(tmp_path))
    engine = create_seeded_engine()

    def fail_if_profile_intake_called(*args, **kwargs):
        raise AssertionError("profile intake should not run for guidance-only profile commands")

    monkeypatch.setattr(command_center_module, "run_profile_intake_extraction", fail_if_profile_intake_called)

    with Session(engine) as session:
        response = command_center_module.execute_command_center_command(
            command_center_module.CommandCenterCommandRequest(
                command="So what should I do?",
                active_workspace="profile",
                clientContext={
                    "transcript": {
                        "messages": [
                            {"role": "user", "type": "message", "text": "Can you help me figure out what roles to target?"},
                            {"role": "assistant", "type": "message", "text": "Which parts of your AI work do you want to do more of?"},
                            {"role": "user", "type": "message", "text": "I like RAG systems and LLM evaluation."},
                            {"role": "assistant", "type": "status", "text": "Status update: previous guidance completed."},
                            {"role": "user", "type": "message", "text": "So what should I do?"},
                        ]
                    }
                },
            ),
            session=session,
        )

        assert session.scalar(select(ProfileFactDraft.id).limit(1)) is None
        assert session.scalar(select(SkillClaim.id).limit(1)) is None
        assert session.scalar(select(ExperienceProjectDraft.id).limit(1)) is None

    assert response.actions[0].type == "profile_guidance"
    assert response.actions[0].status == "completed"
    assert response.actions[0].summary == "Read-only guidance completed. No profile data was changed."
    assert response.status_updates[0].message == "Status update: thinking through guidance without changing saved profile data."
    assert response.result_payload is not None
    assert response.result_payload["ok"] is True
    assert response.result_payload["mutated"] is False
    assert response.result_payload["guidanceContextManifest"]["transcript_text"] == "included"
    assert response.result_payload["guidanceContextManifest"]["transcript_turn_count"] == 5
    assert response.result_payload["modelRequest"]["task"] == "command_center_guidance"
    assert "I like RAG systems and LLM evaluation." in response.result_payload["modelRequest"]["messages"][1]["content"]


def test_profile_guidance_manifest_marks_missing_transcript(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(command_center_module, "load_settings", lambda: make_settings(tmp_path))
    engine = create_seeded_engine()

    with Session(engine) as session:
        response = command_center_module.execute_command_center_command(
            command_center_module.CommandCenterCommandRequest(
                command="What should I put in my headline?",
                active_workspace="profile",
            ),
            session=session,
        )

    assert response.actions[0].type == "profile_guidance"
    assert response.result_payload is not None
    manifest = response.result_payload["guidanceContextManifest"]
    assert manifest["transcript_text"] == "missing"
    assert manifest["transcript_turn_count"] == 0
    assert "clientContext" in manifest["transcript_fallback_reason"]


def test_profile_guidance_manifest_marks_partial_transcript_when_large(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(command_center_module, "load_settings", lambda: make_settings(tmp_path))
    engine = create_seeded_engine()
    huge_middle = "middle context " * 3000

    with Session(engine) as session:
        response = command_center_module.execute_command_center_command(
            command_center_module.CommandCenterCommandRequest(
                command="So what should I do?",
                active_workspace="profile",
                clientContext={
                    "transcript": {
                        "messages": [
                            {"role": "user", "type": "message", "text": "I want help choosing roles."},
                            {"role": "assistant", "type": "message", "text": huge_middle},
                            {"role": "user", "type": "message", "text": "So what should I do?"},
                        ]
                    }
                },
            ),
            session=session,
        )

    assert response.result_payload is not None
    manifest = response.result_payload["guidanceContextManifest"]
    assert manifest["transcript_text"] == "partial"
    assert manifest["transcript_turn_count"] == 3
    assert "exceeded" in manifest["transcript_fallback_reason"]


def test_profile_guidance_does_not_restore_archived_items(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(command_center_module, "load_settings", lambda: make_settings(tmp_path))
    engine = create_seeded_engine()

    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        session.add(
            SkillClaim(
                candidate_profile_id=profile.id,
                skill_name="RAG Systems",
                skill_category="AI Engineering",
                years_min=None,
                years_max=None,
                recency=None,
                proficiency=None,
                evidence_summary=None,
                evidence_fact_ids=[],
                source="model",
                visibility="private",
                verification_status="rejected",
                publication_status="not_published",
            )
        )
        session.commit()

        response = command_center_module.execute_command_center_command(
            command_center_module.CommandCenterCommandRequest(
                command="What should I emphasize?",
                active_workspace="profile",
                clientContext={"transcript": {"messages": [{"role": "user", "type": "message", "text": "What should I emphasize?"}]}},
            ),
            session=session,
        )

        skills = session.scalars(select(SkillClaim)).all()

    assert response.actions[0].type == "profile_guidance"
    assert len(skills) == 1
    assert skills[0].verification_status == "rejected"
    assert response.result_payload is not None
    assert response.result_payload["guidanceContextManifest"]["archived_items"]["count"] == 1


def test_explicit_profile_update_still_uses_mutating_profile_intake(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(command_center_module, "load_settings", lambda: make_settings(tmp_path))
    engine = create_seeded_engine()
    captured = {}

    def fail_if_guidance_called(*args, **kwargs):
        raise AssertionError("guidance should not run for explicit profile update commands")

    def fake_run_profile_intake_extraction(request, *, db_session, settings, candidate_profile=None):
        captured["request"] = request
        return SimpleNamespace(
            status_code=200,
            body={
                "ok": True,
                "result": {
                    "assistantMessage": "Saved suggestion to the private draft.",
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

    monkeypatch.setattr(command_center_module, "run_command_center_guidance", fail_if_guidance_called)
    monkeypatch.setattr(command_center_module, "run_profile_intake_extraction", fake_run_profile_intake_extraction)

    with Session(engine) as session:
        response = command_center_module.execute_command_center_command(
            command_center_module.CommandCenterCommandRequest(
                command="Update my profile with this resume.",
                active_workspace="profile",
            ),
            session=session,
        )

    assert response.actions[0].type == "profile_intake"
    assert response.actions[0].status == "completed"
    assert captured["request"].latest_user_message == "Update my profile with this resume."


def test_command_center_routes_company_url_update_to_company_update(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(command_center_module, "load_settings", lambda: make_settings(tmp_path))
    engine = create_seeded_engine()

    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        company = add_candidate_company(session, profile.id, "CivicActions")
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
        saved = session.get(CandidateCompany, company_id)
        assert response.actions[0].type == "company_update"
        assert response.actions[0].status == "completed"
        assert response.target_workspace == "companies"
        assert response.result_payload is not None
        assert response.result_payload["routerDecision"]["actionType"] == "company_update"
        assert response.result_payload["routerModelRequest"]["task"] == "command_router"
        assert response.result_payload["routerModelRequest"]["searchGrounding"] is False
        assert saved is not None
        assert saved.company.job_listings_url == "https://civicactions.com/careers"


def test_command_with_url_is_not_automatically_add_job_from_url(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(command_center_module, "load_settings", lambda: make_settings(tmp_path))
    engine = create_seeded_engine()

    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        add_candidate_company(session, profile.id, "Higher Ground Labs")
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
        company = add_candidate_company(session, profile.id, "CivicActions")
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
        saved = session.get(CandidateCompany, company_id)
        assert response.actions[0].type == "company_update"
        assert response.actions[0].status == "completed"
        assert saved is not None
        assert saved.company.website_url == "https://civicactions.com"


def test_command_center_add_job_url_executes_url_intake(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(command_center_module, "load_settings", lambda: make_settings(tmp_path))
    engine = create_seeded_engine()

    def fake_run_job_discovery(request, **kwargs):
        return SimpleNamespace(
            body={
                "ok": True,
                "result": {
                    "assistantMessage": "Saved 1 job from the provided URL.",
                    "jobs": [{"id": "saved-job-1"}],
                    "updatedExistingJobs": [],
                    "skippedJobs": [],
                },
            },
            status_code=200,
        )

    monkeypatch.setattr(command_center_module, "run_job_discovery", fake_run_job_discovery)

    with Session(engine) as session:
        response = command_center_module.execute_command_center_command(
            command_center_module.CommandCenterCommandRequest(command="Add this job: https://company.com/jobs/123"),
            session=session,
        )

    assert response.actions[0].type == "add_job_from_url"
    assert response.actions[0].status == "completed"
    assert response.assistant_message == "Saved 1 job from the provided URL."


def test_command_center_stream_lifecycle_logging_is_present() -> None:
    source = Path(command_center_module.__file__).read_text(encoding="utf-8")

    assert "Command-center stream started:" in source
    assert "Command-center stream routed:" in source
    assert "Command-center stream completed:" in source
    assert "Command-center stream failed:" in source


def test_command_stream_event_encodes_database_values() -> None:
    identifier = uuid4()
    emitted_at = datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc)

    event = json.loads(
        command_center_module.command_stream_event(
            "result",
            {
                "result": {
                    "id": identifier,
                    "posting_date": date(2026, 6, 2),
                    "emitted_at": emitted_at,
                }
            },
        )
    )

    assert event["type"] == "result"
    assert event["result"]["id"] == str(identifier)
    assert event["result"]["posting_date"] == "2026-06-02"
    assert event["result"]["emitted_at"] == "2026-06-02T12:00:00+00:00"


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


def add_candidate_company(session: Session, candidate_profile_id: str, name: str) -> CandidateCompany:
    company = upsert_canonical_company(session, name=name, normalized_name=name.casefold())
    result = ensure_candidate_company_link(
        session,
        candidate_profile_id=candidate_profile_id,
        company=company,
        derivation_status="model_derived",
        review_status="new",
    )
    return result.link


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


class DirectUrlPlannerConnector:
    def generate(self, request) -> ModelResponse:
        if request.task == "candidate_db_job_plan_critique":
            return ModelResponse(text=json.dumps({"valid": True}), provider="fake", model="fake")
        return ModelResponse(
            text=json.dumps(
                {
                    "mode": "direct_job_url",
                    "modeRationale": "The user asked to save a specific Greenhouse job URL.",
                    "syncPlan": {
                        "useFollowedCompanyBoards": False,
                        "proposedAdzunaSignatures": [],
                        "existingAdzunaSignatureIdsToRefresh": [],
                    },
                    "dbSearchPlan": {"queries": []},
                    "reviewPlan": {"task": "select_new_jobs", "allowRejections": False},
                }
            ),
            provider="fake",
            model="fake",
        )


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
