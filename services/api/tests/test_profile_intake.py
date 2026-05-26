from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import jobops_api.main as main_module
from jobops_api.auth import SESSION_COOKIE_NAME, create_session_for_username, seed_initial_user
from jobops_api.db.models import (
    Base,
    CandidateProfile,
    EvidenceArtifact,
    ExperienceProjectDraft,
    ProfileFact,
    ProfileFactDraft,
    ProfileFieldValue,
    ProfileIntakeEvent,
    ProfileIntakeSession,
    RoleTarget,
    SkillClaim,
)
from jobops_api.db.seed_profile import seed_public_profile
from jobops_api.db.session import get_db_session
from jobops_api.model_connector import ModelConnector, ModelConnectorConfig, ModelRequest, ModelResponse, ModelRoutingConfig
from jobops_api.profile_intake.models import ProfileIntakeExtractRequest
from jobops_api.profile_intake.persistence import get_or_create_active_intake_session
from jobops_api.profile_intake.service import run_profile_intake_extraction
from jobops_api.profile_fields import get_field_definition, publish_generated_field
from jobops_api.profiles import candidate_profile_to_public_dict
from jobops_api.security import INTERNAL_API_KEY_HEADER
from jobops_api.settings import Settings


class StaticProvider:
    def __init__(self, text: str, finish_reason: str | None = "stop") -> None:
        self.text = text
        self.finish_reason = finish_reason

    def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            finish_reason=self.finish_reason,
            model=request.model,
            provider="test",
            text=self.text,
        )


class RecordingProvider(StaticProvider):
    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return super().generate(request)


class RecordingSequenceProvider:
    def __init__(self, texts: list[str], finish_reason: str | None = "stop", finish_reasons: list[str | None] | None = None) -> None:
        self.texts = texts
        self.finish_reason = finish_reason
        self.finish_reasons = finish_reasons
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        text_index = min(len(self.requests) - 1, len(self.texts) - 1)
        finish_reason = self.finish_reasons[text_index] if self.finish_reasons else self.finish_reason
        return ModelResponse(
            finish_reason=finish_reason,
            model=request.model,
            provider="test",
            text=self.texts[text_index],
        )


def test_fastapi_profile_intake_mock_success(tmp_path: Path) -> None:
    request = ProfileIntakeExtractRequest(latest_user_message="I want to be an Applied AI Engineer focused on remote LLM systems.")

    result = run_profile_intake_extraction(request, settings=make_settings(tmp_path))

    assert result.status_code == 200
    assert result.body["ok"] is True
    output = result.body["result"]
    assert output["targetRoleIntent"]["targetTitles"] == "Applied AI Engineer focused on remote LLM systems"
    assert output["draftFacts"] == []
    assert output["experienceAndProjects"] == []


def test_malformed_model_output_fails_safely(tmp_path: Path) -> None:
    result = run_profile_intake_extraction(
        ProfileIntakeExtractRequest(latest_user_message="I built an eval harness."),
        connector=make_connector(StaticProvider("not json")),
        settings=make_settings(tmp_path),
    )

    assert result.status_code == 502
    assert result.body["ok"] is False
    assert result.body["error"] == "The model returned malformed profile intake data. No draft data was applied."
    assert result.body["issues"] == ["Output is not valid JSON."]
    assert result.body["modelRequest"]["task"] == "profile_draft_update"
    assert result.body["modelRequest"]["messages"][1]["role"] == "user"
    assert result.body["modelResponse"]["text"] == "not json"
    assert "debug_run_id" not in result.body


def test_capacity_validation_failure_returns_specific_error_and_raw_response(tmp_path: Path) -> None:
    over_capacity_output = realistic_resume_output()
    over_capacity_output["changeSummary"] = [f"Change {index}" for index in range(13)]

    result = run_profile_intake_extraction(
        ProfileIntakeExtractRequest(latest_user_message=fake_resume_text()),
        connector=make_connector(StaticProvider(json.dumps(over_capacity_output))),
        settings=make_settings(tmp_path),
    )

    assert result.status_code == 502
    assert result.body["ok"] is False
    assert result.body["code"] == "model_output_exceeded_schema_capacity"
    assert result.body["error"] == (
        "Profile intake model returned more structured items than the current schema allows. No draft data was applied."
    )
    assert "changeSummary: List should have at most 12 items" in " ".join(result.body["issues"])
    assert result.body["modelResponse"]["finishReason"] == "stop"
    assert "Change 12" in result.body["modelResponse"]["text"]


def test_pydantic_validation_failure_rejects_unsafe_generated_metadata(tmp_path: Path) -> None:
    result = run_profile_intake_extraction(
        ProfileIntakeExtractRequest(latest_user_message="I built an eval harness."),
        connector=make_connector(StaticProvider(json.dumps(unsafe_output()))),
        settings=make_settings(tmp_path),
    )

    issue_text = " ".join(result.body["issues"])
    assert result.status_code == 502
    assert "draftFacts.0.status" in issue_text
    assert "draftFacts.0.visibility" in issue_text
    assert "draftFacts.0.published" in issue_text


def test_artifacts_are_disabled_by_default(tmp_path: Path) -> None:
    result = run_profile_intake_extraction(
        ProfileIntakeExtractRequest(latest_user_message="Experience\nApplied AI Engineer\nI built a Python API."),
        settings=make_settings(tmp_path),
    )

    assert result.status_code == 200
    assert not (tmp_path / "artifacts").exists()


def test_metadata_artifacts_are_written_without_raw_text(tmp_path: Path) -> None:
    result = run_profile_intake_extraction(
        ProfileIntakeExtractRequest(
            latest_user_message="Experience\nApplied AI Engineer\nI built a Python API.",
            existing_draft={
                "facts": [{"claim": "Existing draft fact"}],
                "skillClaims": [{"skill": "Python"}],
                "experienceSummaries": [{"title": "Existing project"}],
            },
        ),
        settings=make_settings(tmp_path, save_artifacts=True),
    )

    assert result.status_code == 200
    run_dir = only_run_dir(tmp_path)
    files = {path.name for path in run_dir.iterdir()}
    metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))

    assert {"metadata.json", "request-metadata.json", "parsed-output.json"}.issubset(files)
    assert "prompt.txt" not in files
    assert "raw-response.txt" not in files
    assert metadata["status"] == "success"
    assert metadata["provider"] == "mock"
    assert metadata["input"]["existingDraftFactCount"] == 1
    assert metadata["input"]["existingSkillClaimCount"] == 1
    assert metadata["input"]["existingExperienceAndProjectCount"] == 1

    request_metadata = (run_dir / "request-metadata.json").read_text(encoding="utf-8")
    assert "I built a Python API" not in request_metadata
    assert "Applied AI Engineer" not in request_metadata
    assert "latest_user_message" not in request_metadata
    assert "GEMINI_API_KEY" not in request_metadata


def test_raw_artifacts_are_written_only_when_enabled(tmp_path: Path) -> None:
    result = run_profile_intake_extraction(
        ProfileIntakeExtractRequest(latest_user_message="Experience\nApplied AI Engineer\nI built a Python API."),
        settings=make_settings(tmp_path, save_artifacts=True, save_raw_text=True),
    )

    assert result.status_code == 200
    run_dir = only_run_dir(tmp_path)
    files = {path.name for path in run_dir.iterdir()}

    assert {"metadata.json", "parsed-output.json", "prompt.txt", "raw-response.txt"}.issubset(files)
    assert "latest_user_message" in (run_dir / "prompt.txt").read_text(encoding="utf-8")
    assert "assistantMessage" in (run_dir / "raw-response.txt").read_text(encoding="utf-8")


def test_validation_failure_writes_validation_error_artifact(tmp_path: Path) -> None:
    result = run_profile_intake_extraction(
        ProfileIntakeExtractRequest(latest_user_message="I built an eval harness."),
        connector=make_connector(StaticProvider("not json")),
        settings=make_settings(tmp_path, save_artifacts=True),
    )

    assert result.status_code == 502
    assert result.body["debug_run_id"]
    assert result.body["artifact_path"].startswith("artifacts")
    run_dir = only_run_dir(tmp_path)
    files = {path.name for path in run_dir.iterdir()}
    validation_error = json.loads((run_dir / "validation-error.json").read_text(encoding="utf-8"))

    assert {"metadata.json", "request-metadata.json", "validation-error.json"}.issubset(files)
    assert "raw-response.txt" not in files
    assert validation_error["issues"] == ["Output is not valid JSON."]


def test_artifacts_do_not_include_api_keys_or_secret_env_values(tmp_path: Path) -> None:
    secret = "test-secret-gemini-key"
    result = run_profile_intake_extraction(
        ProfileIntakeExtractRequest(latest_user_message="Experience\nApplied AI Engineer\nI built a Python API."),
        settings=make_settings(tmp_path, save_artifacts=True, save_raw_text=True, gemini_api_key=secret),
    )

    assert result.status_code == 200
    run_dir = only_run_dir(tmp_path)
    contents = "\n".join(path.read_text(encoding="utf-8") for path in run_dir.iterdir() if path.is_file())

    assert secret not in contents


def test_profile_intake_uses_shared_model_connector(tmp_path: Path) -> None:
    provider = RecordingProvider(json.dumps(valid_output()))
    result = run_profile_intake_extraction(
        ProfileIntakeExtractRequest(latest_user_message="I want to be an Applied AI Engineer."),
        connector=make_connector(provider),
        settings=make_settings(tmp_path),
    )

    assert result.status_code == 200
    assert provider.requests
    assert provider.requests[0].task == "profile_draft_update"
    assert provider.requests[0].model == "mock-default"
    assert provider.requests[0].messages[0].role == "system"
    assert provider.requests[0].messages[1].role == "user"


def test_resume_like_input_uses_resume_capacity_and_token_budget(tmp_path: Path) -> None:
    provider = RecordingProvider(json.dumps(valid_output()))

    result = run_profile_intake_extraction(
        ProfileIntakeExtractRequest(latest_user_message=fake_resume_text()),
        connector=make_connector(provider),
        settings=make_settings(tmp_path),
    )

    assert result.status_code == 200
    request = provider.requests[0]
    prompt_payload = json.loads(request.messages[1].content)
    assert request.max_output_tokens == 16000
    assert request.metadata["intake_mode"] == "resume_intake"
    assert "32 facts, 50 skills, 18 experiences, and 20 evidence links" in request.metadata["output_token_budget_reason"]
    assert prompt_payload["detected_intake_mode"] == "resume_intake"
    assert prompt_payload["capacity_guidance"]["active"] == {
        "draftFacts": 32,
        "skillClaims": 50,
        "experienceAndProjects": 18,
        "evidenceLinks": 20,
        "clarifyingQuestions": 6,
        "changeSummary": 12,
    }
    system_prompt = request.messages[0].content
    assert "Put education and certifications in experienceAndProjects, not draftFacts." in system_prompt
    assert 'Use itemType "education"' in system_prompt
    assert 'Use itemType "certification"' in system_prompt
    assert "Preserve month/year precision when the resume gives it" in system_prompt
    assert "put it in location instead of summary" in system_prompt


def test_resume_headings_and_en_dash_dates_use_resume_mode(tmp_path: Path) -> None:
    provider = RecordingProvider(json.dumps(valid_output()))

    result = run_profile_intake_extraction(
        ProfileIntakeExtractRequest(latest_user_message=resume_text_without_resume_label()),
        connector=make_connector(provider),
        settings=make_settings(tmp_path),
    )

    assert result.status_code == 200
    assert provider.requests[0].metadata["intake_mode"] == "resume_intake"
    assert provider.requests[0].max_output_tokens == 16000


def test_short_chat_input_uses_compact_capacity(tmp_path: Path) -> None:
    provider = RecordingProvider(json.dumps(valid_output()))

    result = run_profile_intake_extraction(
        ProfileIntakeExtractRequest(latest_user_message="I want to be an Applied AI Engineer."),
        connector=make_connector(provider),
        settings=make_settings(tmp_path),
    )

    assert result.status_code == 200
    request = provider.requests[0]
    prompt_payload = json.loads(request.messages[1].content)
    assert request.max_output_tokens == 5000
    assert request.metadata["intake_mode"] == "chat_update"
    assert prompt_payload["detected_intake_mode"] == "chat_update"
    assert prompt_payload["capacity_guidance"]["active"] == {
        "draftFacts": 4,
        "skillClaims": 6,
        "experienceAndProjects": 3,
        "evidenceLinks": 4,
        "clarifyingQuestions": 3,
        "changeSummary": 3,
    }


def test_truncated_resume_response_retries_with_compact_resume_budget(tmp_path: Path) -> None:
    full_response = json.dumps(realistic_resume_output())
    truncated_response = full_response[:4000]
    provider = RecordingSequenceProvider(
        [truncated_response, json.dumps(valid_output())],
        finish_reasons=["MAX_TOKENS", "stop"],
    )

    result = run_profile_intake_extraction(
        ProfileIntakeExtractRequest(latest_user_message=fake_resume_text()),
        connector=make_connector(provider),
        settings=make_settings(tmp_path, save_artifacts=True, save_raw_text=True),
    )

    assert result.status_code == 200
    assert result.body["ok"] is True
    assert len(provider.requests) == 2
    assert provider.requests[0].max_output_tokens == 16000
    assert provider.requests[1].max_output_tokens == 12000
    assert provider.requests[1].metadata["compact_resume_retry"] is True
    retry_prompt = json.loads(provider.requests[1].messages[1].content)
    assert retry_prompt["compact_resume_retry"] is True
    assert retry_prompt["capacity_guidance"]["active"] == {
        "draftFacts": 12,
        "skillClaims": 20,
        "experienceAndProjects": 8,
        "evidenceLinks": 8,
        "clarifyingQuestions": 3,
        "changeSummary": 6,
    }
    assert result.body["modelRequest"]["maxOutputTokens"] == 12000
    assert result.body["modelResponse"]["finishReason"] == "stop"
    run_dir = only_run_dir(tmp_path)
    assert (run_dir / "raw-response-truncated-before-retry.txt").exists()
    assert (run_dir / "request-metadata-compact-retry.json").exists()


def test_truncated_resume_retry_failure_returns_specific_actionable_error(tmp_path: Path) -> None:
    full_response = json.dumps(realistic_resume_output())
    truncated_response = full_response[:4000]

    result = run_profile_intake_extraction(
        ProfileIntakeExtractRequest(latest_user_message=fake_resume_text()),
        connector=make_connector(StaticProvider(truncated_response, finish_reason="MAX_TOKENS")),
        settings=make_settings(tmp_path, save_artifacts=True),
    )

    assert result.status_code == 502
    assert result.body["ok"] is False
    assert result.body["code"] == "model_response_truncated"
    assert result.body["error"] == (
        "Profile intake model response was truncated before valid JSON completed. No draft data was applied."
    )
    assert "Model response appears to have been truncated before valid JSON completed." in result.body["issues"]
    assert result.body["modelRequest"]["maxOutputTokens"] == 12000
    assert result.body["modelResponse"]["finishReason"] == "MAX_TOKENS"
    run_dir = only_run_dir(tmp_path)
    validation_error = json.loads((run_dir / "validation-error.json").read_text(encoding="utf-8"))
    assert "truncated" in " ".join(validation_error["issues"]).lower()


def test_api_endpoint_uses_fastapi_profile_intake_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    monkeypatch.setattr(main_module, "settings", make_settings(tmp_path))
    session_factory = make_seeded_session_factory()
    main_module.app.dependency_overrides[get_db_session] = override_session_dependency(session_factory)
    client = TestClient(main_module.app)
    session_token = create_auth_session_token(session_factory)

    try:
        response = client.post(
            "/v1/profile-intake/extract",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
            cookies={SESSION_COOKIE_NAME: session_token},
            json={"latest_user_message": "I want to be an Applied AI Engineer."},
        )
    finally:
        main_module.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["result"]["targetRoleIntent"]["targetTitles"] == "Applied AI Engineer"


def test_get_or_create_active_intake_session_reuses_existing_session() -> None:
    session_factory = make_seeded_session_factory()

    with session_factory() as session:
        profile = seeded_profile(session)
        first = get_or_create_active_intake_session(session, profile.id)
        session.commit()
        second = get_or_create_active_intake_session(session, profile.id)

        assert first.id == second.id


def test_persisted_profile_intake_success_saves_private_drafts_and_redacted_events(tmp_path: Path) -> None:
    session_factory = make_seeded_session_factory()

    with session_factory() as session:
        result = run_profile_intake_extraction(
            ProfileIntakeExtractRequest(latest_user_message="Experience\nI built a Python FastAPI eval harness."),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    assert result.status_code == 200
    assert result.body["ok"] is True
    assert result.body["result"]["draftFacts"]

    with session_factory() as session:
        intake_session = session.scalar(select(ProfileIntakeSession).where(ProfileIntakeSession.status == "active"))
        assert intake_session is not None

        fact = session.scalars(select(ProfileFactDraft)).first()
        skill = session.scalars(select(SkillClaim)).first()
        experience = session.scalars(select(ExperienceProjectDraft)).one()
        events = session.scalars(select(ProfileIntakeEvent).order_by(ProfileIntakeEvent.created_at)).all()

        assert fact is not None
        assert fact.review_status == "needs_review"
        assert fact.suggested_visibility == "private"
        assert fact.structured_value["published"] is False
        assert skill is not None
        assert skill.verification_status == "draft"
        assert skill.visibility == "private"
        assert skill.publication_status == "not_published"
        assert experience.visibility == "private"
        assert experience.review_status == "needs_review"
        assert experience.publication_status == "not_published"
        assert {event.role for event in events} == {"user", "assistant"}
        assert all(event.redacted_text is None for event in events)
        assert all("I built a Python FastAPI eval harness" not in json.dumps(event.event_metadata) for event in events)


def test_persisted_resume_intake_accepts_realistic_complete_draft(tmp_path: Path) -> None:
    session_factory = make_seeded_session_factory()
    provider = RecordingProvider(json.dumps(realistic_resume_output()))

    with session_factory() as session:
        result = run_profile_intake_extraction(
            ProfileIntakeExtractRequest(latest_user_message=fake_resume_text()),
            connector=make_connector(provider),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    assert result.status_code == 200
    snapshot = result.body["result"]
    assert len(snapshot["draftFacts"]) == 16
    assert len(snapshot["skillClaims"]) == 28
    assert len(snapshot["experienceAndProjects"]) == 9
    assert len(snapshot["evidenceLinks"]) == 9
    assert len(snapshot["clarifyingQuestions"]) == 4
    assert len(snapshot["changeSummary"]) == 6
    assert provider.requests[0].metadata["intake_mode"] == "resume_intake"

    with session_factory() as session:
        facts = session.scalars(select(ProfileFactDraft)).all()
        skills = session.scalars(select(SkillClaim)).all()
        experiences = session.scalars(select(ExperienceProjectDraft)).all()
        evidence = session.scalars(select(EvidenceArtifact)).all()

        assert len(facts) == 16
        assert len(skills) == 28
        assert len(experiences) == 9
        assert len(evidence) == 9
        assert experiences[0].start_date == "2022"
        assert experiences[0].end_date == "Present"
        assert experiences[0].location == "Remote"
        assert experiences[0].structured_value["itemType"] == "experience"
        assert experiences[0].structured_value["startDate"] == "2022"
        assert experiences[0].structured_value["endDate"] == "Present"
        assert experiences[0].structured_value["location"] == "Remote"
        assert experiences[0].structured_value["bullets"] == [
            "Built an LLM evaluation platform for support automation.",
            "Led Python and FastAPI services that processed workflow data.",
        ]
        assert all(fact.review_status == "needs_review" for fact in facts)
        assert all(skill.visibility == "private" and skill.publication_status == "not_published" for skill in skills)
        assert all(item.visibility == "private" and item.publication_status == "not_published" for item in experiences)
        assert all(item.visibility == "private" and item.publication_status == "not_published" for item in evidence)


def test_persisted_evidence_links_remain_private_and_unpublished(tmp_path: Path) -> None:
    session_factory = make_seeded_session_factory()

    with session_factory() as session:
        result = run_profile_intake_extraction(
            ProfileIntakeExtractRequest(latest_user_message="Experience\nProject: https://example.com/jobops"),
            connector=make_connector(StaticProvider(json.dumps(valid_output_with_evidence()))),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    assert result.status_code == 200

    with session_factory() as session:
        evidence = session.scalars(select(EvidenceArtifact)).one()

        assert evidence.visibility == "private"
        assert evidence.review_status == "needs_review"
        assert evidence.publication_status == "not_published"


def test_profile_intake_second_empty_turn_preserves_merged_saved_draft(tmp_path: Path) -> None:
    session_factory = make_seeded_session_factory()

    with session_factory() as session:
        first_result = run_profile_intake_extraction(
            ProfileIntakeExtractRequest(latest_user_message="I target applied AI roles and shipped JobOps."),
            connector=make_connector(StaticProvider(json.dumps(full_profile_intake_output()))),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    assert first_result.status_code == 200
    assert first_result.body["result"]["targetRoleIntent"]["targetTitles"] == "Applied AI Engineer"
    assert len(first_result.body["result"]["draftFacts"]) == 1
    assert len(first_result.body["result"]["skillClaims"]) == 1
    assert len(first_result.body["result"]["experienceAndProjects"]) == 1
    assert len(first_result.body["result"]["evidenceLinks"]) == 1

    with session_factory() as session:
        role_target = session.scalars(select(RoleTarget)).one()
        fact = session.scalars(select(ProfileFactDraft)).one()
        skill = session.scalars(select(SkillClaim)).one()
        experience = session.scalars(select(ExperienceProjectDraft)).one()
        evidence = session.scalars(select(EvidenceArtifact)).one()
        role_target_id = role_target.id

        role_target.review_status = "approved"
        role_target.visibility = "public"
        role_target.publication_status = "published"
        fact.review_status = "approved"
        fact.suggested_visibility = "public"
        fact.structured_value = {"published": True, "sourceStatus": "needs_review"}
        skill.verification_status = "approved"
        skill.visibility = "public"
        skill.publication_status = "published"
        experience.review_status = "approved"
        experience.visibility = "public"
        experience.publication_status = "published"
        experience.structured_value = {"published": True, "sourceStatus": "needs_review"}
        evidence.review_status = "approved"
        evidence.visibility = "public"
        evidence.publication_status = "published"
        evidence.artifact_metadata = {"published": True, "sourceStatus": "needs_review"}
        session.commit()

    with session_factory() as session:
        second_result = run_profile_intake_extraction(
            ProfileIntakeExtractRequest(latest_user_message="Anything else?"),
            connector=make_connector(StaticProvider(json.dumps(empty_patch_output()))),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    assert second_result.status_code == 200
    snapshot = second_result.body["result"]
    assert snapshot["targetRoleIntent"]["targetTitles"] == "Applied AI Engineer"
    assert snapshot["targetRoleIntent"]["preferredWorkMode"] == "remote"
    assert snapshot["draftFacts"][0]["claim"] == "Built a production FastAPI service for JobOps."
    assert snapshot["draftFacts"][0]["status"] == "approved"
    assert snapshot["draftFacts"][0]["visibility"] == "public"
    assert snapshot["draftFacts"][0]["published"] is True
    assert snapshot["skillClaims"][0]["evidence"] == "Used Python and FastAPI in the JobOps backend."
    assert snapshot["skillClaims"][0]["published"] is True
    assert snapshot["experienceAndProjects"][0]["summary"] == "Built the profile intake persistence path."
    assert snapshot["experienceAndProjects"][0]["published"] is True
    assert snapshot["evidenceLinks"][0]["url"] == "https://example.com/jobops"
    assert snapshot["evidenceLinks"][0]["published"] is True

    with session_factory() as session:
        intake_session = session.scalars(select(ProfileIntakeSession)).one()
        counts = intake_session.redacted_state["draftCounts"]
        assert counts == {
            "draftFactCount": 1,
            "skillClaimCount": 1,
            "experienceAndProjectCount": 1,
            "evidenceLinkCount": 1,
        }
        assert {row.id for row in session.scalars(select(RoleTarget)).all()} == {role_target_id}
        assert len(session.scalars(select(ProfileFactDraft)).all()) == 1
        assert len(session.scalars(select(SkillClaim)).all()) == 1
        assert len(session.scalars(select(ExperienceProjectDraft)).all()) == 1
        assert len(session.scalars(select(EvidenceArtifact)).all()) == 1


def test_profile_intake_merge_adds_new_facts_and_dedupes_without_clearing_fields(tmp_path: Path) -> None:
    session_factory = make_seeded_session_factory()

    with session_factory() as session:
        run_profile_intake_extraction(
            ProfileIntakeExtractRequest(latest_user_message="I built JobOps with Python."),
            connector=make_connector(StaticProvider(json.dumps(dedupe_initial_output()))),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    with session_factory() as session:
        result = run_profile_intake_extraction(
            ProfileIntakeExtractRequest(latest_user_message="I also created LLM evals."),
            connector=make_connector(StaticProvider(json.dumps(dedupe_patch_output()))),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    assert result.status_code == 200
    snapshot = result.body["result"]
    assert [fact["claim"] for fact in snapshot["draftFacts"]] == [
        "Built a production FastAPI service for JobOps.",
        "Created LLM regression evals for profile intake.",
    ]
    assert len(snapshot["skillClaims"]) == 1
    assert snapshot["skillClaims"][0]["evidence"] == "Used Python and FastAPI in the JobOps backend."
    assert len(snapshot["experienceAndProjects"]) == 1
    assert snapshot["experienceAndProjects"][0]["organization"] == "Independent"
    assert snapshot["experienceAndProjects"][0]["summary"] == "Built the profile intake persistence path."
    assert len(snapshot["evidenceLinks"]) == 1

    with session_factory() as session:
        assert len(session.scalars(select(ProfileFactDraft)).all()) == 2
        assert len(session.scalars(select(SkillClaim)).all()) == 1
        assert len(session.scalars(select(ExperienceProjectDraft)).all()) == 1
        assert len(session.scalars(select(EvidenceArtifact)).all()) == 1
        intake_session = session.scalars(select(ProfileIntakeSession)).one()
        assert intake_session.redacted_state["latestDraftSnapshot"]["draftFacts"] == snapshot["draftFacts"]
        assert intake_session.redacted_state["draftCounts"]["draftFactCount"] == 2


def test_profile_intake_can_create_generated_profile_basics_fields(tmp_path: Path) -> None:
    session_factory = make_seeded_session_factory()

    with session_factory() as session:
        result = run_profile_intake_extraction(
            ProfileIntakeExtractRequest(latest_user_message="Use Rebekah Love, Applied AI builder, and a short summary."),
            connector=make_connector(StaticProvider(json.dumps(profile_basics_output()))),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    assert result.status_code == 200
    assert result.body["result"]["profileBasics"]["displayName"] == "Rebekah Love"
    with session_factory() as session:
        rows = list(session.scalars(select(ProfileFieldValue).where(ProfileFieldValue.field_group == "profile_basics")))
        values = {row.field_name: row for row in rows}
        assert values["displayName"].value_text == "Rebekah Love"
        assert values["displayName"].lifecycle_status == "generated"
        assert values["displayName"].visibility is None
        assert values["headline"].value_text == "Applied AI builder"
        profile = session.scalars(select(CandidateProfile)).one()
        public_snapshot = candidate_profile_to_public_dict(profile)
        assert public_snapshot["displayName"] == ""
        publish_generated_field(session, profile, values["displayName"], get_field_definition("profile_basics", "displayName"), "public")
        session.flush()
        public_snapshot = candidate_profile_to_public_dict(profile)
        assert public_snapshot["displayName"] == "Rebekah Love"


def test_profile_intake_can_update_existing_generated_profile_basics_fields(tmp_path: Path) -> None:
    session_factory = make_seeded_session_factory()

    with session_factory() as session:
        run_profile_intake_extraction(
            ProfileIntakeExtractRequest(latest_user_message="Draft my basics."),
            connector=make_connector(StaticProvider(json.dumps(profile_basics_output()))),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    provider = RecordingProvider(json.dumps(profile_basics_update_output()))
    with session_factory() as session:
        result = run_profile_intake_extraction(
            ProfileIntakeExtractRequest(latest_user_message="Change my headline to AI systems engineer."),
            connector=make_connector(provider),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    assert result.status_code == 200
    prompt_payload = json.loads(provider.requests[0].messages[1].content)
    assert prompt_payload["authoritative_current_draft"]["profileBasics"]["headline"] == "Applied AI builder"
    with session_factory() as session:
        headline_rows = list(
            session.scalars(
                select(ProfileFieldValue).where(
                    ProfileFieldValue.field_group == "profile_basics",
                    ProfileFieldValue.field_name == "headline",
                )
            )
        )
        assert len(headline_rows) == 1
        assert headline_rows[0].value_text == "AI systems engineer"


def test_profile_intake_can_create_and_update_target_profile_fields(tmp_path: Path) -> None:
    session_factory = make_seeded_session_factory()

    with session_factory() as session:
        run_profile_intake_extraction(
            ProfileIntakeExtractRequest(latest_user_message="I want applied AI roles in Louisville."),
            connector=make_connector(StaticProvider(json.dumps(louisville_target_role_output()))),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    with session_factory() as session:
        run_profile_intake_extraction(
            ProfileIntakeExtractRequest(latest_user_message="Add London too."),
            connector=make_connector(StaticProvider(json.dumps(london_additive_target_role_output()))),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    with session_factory() as session:
        rows = list(session.scalars(select(ProfileFieldValue).where(ProfileFieldValue.field_group == "targets")))
        values = {row.field_name: row.value_text for row in rows}
        assert values["targetTitles"] == "Applied AI Engineer"
        assert values["roleFamilies"] == "Applied AI"
        assert values["preferredLocations"] == "Louisville, KY; London, UK"
        role_target = session.scalars(select(RoleTarget)).one()
        assert role_target.preferred_locations == ["Louisville, KY", "London, UK"]


def test_profile_intake_model_receives_authoritative_saved_draft_for_additive_turn(tmp_path: Path) -> None:
    session_factory = make_seeded_session_factory()
    provider = RecordingSequenceProvider(
        [
            json.dumps(louisville_target_role_output()),
            json.dumps(london_additive_target_role_output()),
        ]
    )

    with session_factory() as session:
        first_result = run_profile_intake_extraction(
            ProfileIntakeExtractRequest(
                latest_user_message="I want to be an Applied AI Engineer, remote or on-location/hybrid from Louisville, KY"
            ),
            connector=make_connector(provider),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    assert first_result.status_code == 200
    assert first_result.body["result"]["targetRoleIntent"]["targetTitles"] == "Applied AI Engineer"
    assert first_result.body["result"]["targetRoleIntent"]["preferredLocations"] == "Louisville, KY"

    with session_factory() as session:
        second_result = run_profile_intake_extraction(
            ProfileIntakeExtractRequest(
                latest_user_message="or maybe on location in London, UK as well",
                existing_draft={"targetRoleIntent": {"preferredLocations": "Paris, France"}},
            ),
            connector=make_connector(provider),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    assert second_result.status_code == 200
    snapshot = second_result.body["result"]
    assert snapshot["targetRoleIntent"]["targetTitles"] == "Applied AI Engineer"
    assert snapshot["targetRoleIntent"]["preferredLocations"] == "Louisville, KY; London, UK"

    second_prompt = json.loads(provider.requests[1].messages[1].content)
    assert second_prompt["authoritative_current_draft_source"] == "database"
    assert second_prompt["authoritative_current_draft"]["targetRoleIntent"]["preferredLocations"] == "Louisville, KY"
    assert second_prompt["client_existing_draft"]["targetRoleIntent"]["preferredLocations"] == "Paris, France"
    assert second_prompt["task"] == "update_profile_draft"
    assert second_prompt["update_rules"]["return_full_updated_draft"] is True
    assert second_prompt["update_rules"]["backend_interprets_additive_or_replacement_language"] is False
    assert (
        second_prompt["update_rules"]["examples"][0]["expected_output_preferredLocations"]
        == "London, UK; NYC; San Francisco Bay"
    )
    assert provider.requests[1].metadata["authoritative_current_draft_source"] == "database"
    assert provider.requests[1].metadata["client_existing_draft_included"] is True

    with session_factory() as session:
        role_target = session.scalars(select(RoleTarget)).one()
        assert role_target.preferred_locations == ["Louisville, KY", "London, UK"]
        intake_session = session.scalars(select(ProfileIntakeSession)).one()
        assert intake_session.redacted_state["input"]["currentDraftFactCount"] == 0
        assert intake_session.redacted_state["input"]["currentSkillClaimCount"] == 0
        assert intake_session.redacted_state["input"]["currentExperienceAndProjectCount"] == 0
        assert intake_session.redacted_state["input"]["currentEvidenceLinkCount"] == 0


def test_profile_intake_client_existing_draft_cannot_override_database_state(tmp_path: Path) -> None:
    session_factory = make_seeded_session_factory()

    with session_factory() as session:
        run_profile_intake_extraction(
            ProfileIntakeExtractRequest(latest_user_message="I want Louisville in my target locations."),
            connector=make_connector(StaticProvider(json.dumps(louisville_target_role_output()))),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    provider = RecordingProvider(json.dumps(empty_patch_output()))
    with session_factory() as session:
        result = run_profile_intake_extraction(
            ProfileIntakeExtractRequest(
                latest_user_message="Anything else?",
                existing_draft={"targetRoleIntent": {"preferredLocations": "Paris, France"}},
            ),
            connector=make_connector(provider),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    assert result.status_code == 200
    assert result.body["result"]["targetRoleIntent"]["preferredLocations"] == "Louisville, KY"
    prompt_payload = json.loads(provider.requests[0].messages[1].content)
    assert prompt_payload["authoritative_current_draft"]["targetRoleIntent"]["preferredLocations"] == "Louisville, KY"
    assert prompt_payload["client_existing_draft"]["targetRoleIntent"]["preferredLocations"] == "Paris, France"


def test_profile_intake_replacement_language_can_update_target_role_field(tmp_path: Path) -> None:
    session_factory = make_seeded_session_factory()

    with session_factory() as session:
        run_profile_intake_extraction(
            ProfileIntakeExtractRequest(latest_user_message="I want Louisville in my target locations."),
            connector=make_connector(StaticProvider(json.dumps(louisville_target_role_output()))),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    with session_factory() as session:
        result = run_profile_intake_extraction(
            ProfileIntakeExtractRequest(latest_user_message="Actually, change the location to London, UK instead."),
            connector=make_connector(StaticProvider(json.dumps(london_replacement_target_role_output()))),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    assert result.status_code == 200
    assert result.body["result"]["targetRoleIntent"]["preferredLocations"] == "London, UK"

    with session_factory() as session:
        role_target = session.scalars(select(RoleTarget)).one()
        assert role_target.preferred_locations == ["London, UK"]


def test_profile_intake_additive_language_preserves_list_like_role_intent_fields(tmp_path: Path) -> None:
    session_factory = make_seeded_session_factory()

    with session_factory() as session:
        run_profile_intake_extraction(
            ProfileIntakeExtractRequest(latest_user_message="I want to be an Applied AI Engineer in developer tools."),
            connector=make_connector(StaticProvider(json.dumps(louisville_target_role_output()))),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    with session_factory() as session:
        result = run_profile_intake_extraction(
            ProfileIntakeExtractRequest(
                latest_user_message="I'd also consider AI Product Engineer roles in healthcare."
            ),
            connector=make_connector(StaticProvider(json.dumps(additive_role_intent_output()))),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    assert result.status_code == 200
    intent = result.body["result"]["targetRoleIntent"]
    assert "Applied AI Engineer" in intent["targetTitles"]
    assert "AI Product Engineer" in intent["targetTitles"]
    assert intent["domainsOrIndustries"] == "developer tools; healthcare"


def test_profile_intake_model_final_state_handles_terse_location_alternatives(tmp_path: Path) -> None:
    session_factory = make_seeded_session_factory()

    with session_factory() as session:
        run_profile_intake_extraction(
            ProfileIntakeExtractRequest(latest_user_message="I want to work onsite in London, UK."),
            connector=make_connector(StaticProvider(json.dumps(london_replacement_target_role_output()))),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    provider = RecordingProvider(json.dumps(london_nyc_sf_final_state_output()))
    with session_factory() as session:
        result = run_profile_intake_extraction(
            ProfileIntakeExtractRequest(latest_user_message="or NYC or San Francisco Bay"),
            connector=make_connector(provider),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    assert result.status_code == 200
    assert result.body["result"]["targetRoleIntent"]["preferredLocations"] == "London, UK; NYC; San Francisco Bay"
    prompt_payload = json.loads(provider.requests[0].messages[1].content)
    assert prompt_payload["authoritative_current_draft"]["targetRoleIntent"]["preferredLocations"] == "London, UK"
    assert (
        prompt_payload["update_rules"]["target_role_intent_update_contract"]
        .startswith("Return full targetRoleIntent after the latest message")
    )


def test_profile_intake_full_draft_sync_preserves_ids_and_status_metadata(tmp_path: Path) -> None:
    session_factory = make_seeded_session_factory()

    with session_factory() as session:
        first = run_profile_intake_extraction(
            ProfileIntakeExtractRequest(latest_user_message="I saved a full draft."),
            connector=make_connector(StaticProvider(json.dumps(full_profile_intake_output()))),
            db_session=session,
            settings=make_settings(tmp_path),
        )
        assert first.status_code == 200

        fact = session.scalars(select(ProfileFactDraft)).one()
        skill = session.scalars(select(SkillClaim)).one()
        experience = session.scalars(select(ExperienceProjectDraft)).one()
        evidence = session.scalars(select(EvidenceArtifact)).one()

        fact.review_status = "approved"
        fact.suggested_visibility = "public"
        skill.verification_status = "approved"
        skill.visibility = "public"
        experience.review_status = "approved"
        experience.visibility = "public"
        evidence.review_status = "approved"
        evidence.visibility = "public"
        session.commit()

        update = full_profile_intake_output()
        draft = update["updatedDraftProfile"]
        draft["draftFacts"] = [
            {
                "id": fact.id,
                "claim": "Built and operated a production FastAPI service for JobOps.",
                "category": "backend",
                "source": "chat",
                "status": "needs_review",
                "visibility": "private",
                "published": False,
            },
            {
                "claim": "Created regression checks for LLM profile intake.",
                "category": "evals",
                "source": "chat",
                "status": "needs_review",
                "visibility": "private",
                "published": False,
            },
        ]
        draft["skillClaims"] = [
            {
                "id": skill.id,
                "skill": "Python",
                "category": "programming language",
                "evidence": "Used Python to build the JobOps API.",
                "source": "chat",
                "status": "draft",
                "visibility": "private",
                "published": False,
            },
            {
                "skill": "LLM evals",
                "category": "ai_systems",
                "evidence": "Created regression checks for profile intake.",
                "source": "chat",
                "status": "draft",
                "visibility": "private",
                "published": False,
            },
        ]
        draft["experienceAndProjects"] = [
            {
                "id": experience.id,
                "title": "JobOps",
                "organization": "Independent",
                "summary": "Built the full-draft profile intake path.",
                "source": "chat",
                "status": "needs_review",
                "visibility": "private",
                "published": False,
            }
        ]
        draft["evidenceLinks"] = [
            {
                "id": evidence.id,
                "url": "https://example.com/jobops",
                "label": "Updated JobOps project",
                "source": "chat",
                "status": "needs_review",
                "visibility": "private",
                "published": False,
            }
        ]

    with session_factory() as session:
        result = run_profile_intake_extraction(
            ProfileIntakeExtractRequest(latest_user_message="Update the saved draft with these refinements."),
            connector=make_connector(StaticProvider(json.dumps(update))),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    assert result.status_code == 200
    snapshot = result.body["result"]
    assert snapshot["draftFacts"][0]["id"] == fact.id
    assert snapshot["draftFacts"][0]["claim"] == "Built and operated a production FastAPI service for JobOps."
    assert snapshot["draftFacts"][0]["status"] == "approved"
    assert snapshot["draftFacts"][0]["visibility"] == "public"
    assert len(snapshot["draftFacts"]) == 2
    assert snapshot["skillClaims"][0]["id"] == skill.id
    assert snapshot["skillClaims"][0]["evidence"] == "Used Python to build the JobOps API."
    assert snapshot["skillClaims"][0]["status"] == "approved"
    assert snapshot["skillClaims"][0]["visibility"] == "public"
    assert len(snapshot["skillClaims"]) == 2
    assert snapshot["experienceAndProjects"][0]["id"] == experience.id
    assert snapshot["experienceAndProjects"][0]["summary"] == "Built the full-draft profile intake path."
    assert snapshot["experienceAndProjects"][0]["status"] == "approved"
    assert snapshot["evidenceLinks"][0]["id"] == evidence.id
    assert snapshot["evidenceLinks"][0]["label"] == "Updated JobOps project"
    assert snapshot["evidenceLinks"][0]["visibility"] == "public"


def test_profile_intake_omitted_items_are_preserved_without_explicit_removal(tmp_path: Path) -> None:
    session_factory = make_seeded_session_factory()

    with session_factory() as session:
        run_profile_intake_extraction(
            ProfileIntakeExtractRequest(latest_user_message="I saved a full draft."),
            connector=make_connector(StaticProvider(json.dumps(full_profile_intake_output()))),
            db_session=session,
            settings=make_settings(tmp_path),
        )
        fact_id = session.scalars(select(ProfileFactDraft)).one().id

    update = profile_update_output(
        assistant_message="The request was ambiguous, so I left the draft unchanged.",
        draft={
            "targetRoleIntent": {
                "targetTitles": "Applied AI Engineer",
                "targetRoleFamilies": "Applied AI",
                "preferredWorkMode": "remote",
                "preferredLocations": "New York",
                "domainsOrIndustries": "developer tools",
                "constraints": "No onsite-only roles",
            },
            "draftFacts": [],
            "skillClaims": [],
            "experienceAndProjects": [],
            "evidenceLinks": [],
        },
        clarifying_questions=["Did you want me to change the profile draft?"],
        change_summary=[],
        no_change_reason="The latest message did not clearly request a profile update.",
    )

    with session_factory() as session:
        result = run_profile_intake_extraction(
            ProfileIntakeExtractRequest(latest_user_message="maybe that"),
            connector=make_connector(StaticProvider(json.dumps(update))),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    assert result.status_code == 200
    assert result.body["result"]["draftFacts"][0]["id"] == fact_id
    assert result.body["result"]["clarifyingQuestions"] == ["Did you want me to change the profile draft?"]
    assert result.body["result"]["noChangeReason"] == "The latest message did not clearly request a profile update."


def test_profile_intake_explicit_removed_items_delete_private_drafts(tmp_path: Path) -> None:
    session_factory = make_seeded_session_factory()

    with session_factory() as session:
        run_profile_intake_extraction(
            ProfileIntakeExtractRequest(latest_user_message="I saved a full draft."),
            connector=make_connector(StaticProvider(json.dumps(full_profile_intake_output()))),
            db_session=session,
            settings=make_settings(tmp_path),
        )
        fact = session.scalars(select(ProfileFactDraft)).one()
        removed_fact_id = fact.id
        kept_draft = full_profile_intake_output()
        kept_draft["updatedDraftProfile"]["draftFacts"] = []
        kept_draft["removedItems"]["draftFactIds"] = [removed_fact_id]
        kept_draft["changeSummary"] = ["Removed the requested draft fact."]

    with session_factory() as session:
        result = run_profile_intake_extraction(
            ProfileIntakeExtractRequest(latest_user_message="Remove that draft fact."),
            connector=make_connector(StaticProvider(json.dumps(kept_draft))),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    assert result.status_code == 200
    assert result.body["result"]["draftFacts"] == []
    with session_factory() as session:
        assert session.scalars(select(ProfileFactDraft)).all() == []


def test_profile_intake_seeds_editable_draft_from_published_role_target_without_mutating_published(
    tmp_path: Path,
) -> None:
    session_factory = make_seeded_session_factory()

    with session_factory() as session:
        profile = seeded_profile(session)
        session.add(
            RoleTarget(
                candidate_profile_id=profile.id,
                profile_intake_session_id=None,
                target_titles=["Applied AI Engineer"],
                role_families=["Applied AI"],
                preferred_locations=["Louisville, KY"],
                work_modes=["remote"],
                constraints={"domainsOrIndustries": "developer tools"},
                source="chat",
                review_status="approved",
                visibility="public",
                publication_status="published",
                is_active=True,
            )
        )
        session.add(
            ProfileFact(
                candidate_profile_id=profile.id,
                fact_type="general",
                claim="Published profile fact stays immutable.",
                structured_value={},
                source="seed",
                visibility="public",
                verification_status="published",
            )
        )
        session.commit()

    provider = RecordingProvider(json.dumps(london_additive_target_role_output()))
    with session_factory() as session:
        result = run_profile_intake_extraction(
            ProfileIntakeExtractRequest(latest_user_message="or maybe on location in London, UK as well"),
            connector=make_connector(provider),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    assert result.status_code == 200
    assert result.body["result"]["targetRoleIntent"]["preferredLocations"] == "Louisville, KY; London, UK"
    prompt_payload = json.loads(provider.requests[0].messages[1].content)
    assert prompt_payload["authoritative_current_draft"]["targetRoleIntent"]["preferredLocations"] == "Louisville, KY"
    assert provider.requests[0].metadata["seeded_editable_draft_from_published"] is True

    with session_factory() as session:
        published_role_target = session.scalar(select(RoleTarget).where(RoleTarget.publication_status == "published"))
        draft_role_target = session.scalar(select(RoleTarget).where(RoleTarget.publication_status == "not_published"))
        assert published_role_target is not None
        assert published_role_target.profile_intake_session_id is None
        assert published_role_target.preferred_locations == ["Louisville, KY"]
        assert published_role_target.visibility == "public"
        assert draft_role_target is not None
        assert draft_role_target.profile_intake_session_id is not None
        assert draft_role_target.preferred_locations == ["Louisville, KY", "London, UK"]
        assert draft_role_target.visibility == "private"
        published_fact = session.scalars(select(ProfileFact)).one()
        draft_fact = session.scalars(select(ProfileFactDraft)).one()
        assert published_fact.verification_status == "published"
        assert published_fact.visibility == "public"
        assert draft_fact.claim == published_fact.claim
        assert draft_fact.structured_value["derivedFromPublishedFactId"] == published_fact.id


def test_malformed_model_output_does_not_persist_drafts(tmp_path: Path) -> None:
    session_factory = make_seeded_session_factory()

    with session_factory() as session:
        result = run_profile_intake_extraction(
            ProfileIntakeExtractRequest(latest_user_message="I built an eval harness."),
            connector=make_connector(StaticProvider("not json")),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    assert result.status_code == 502

    with session_factory() as session:
        assert session.scalars(select(ProfileFactDraft)).all() == []
        assert session.scalars(select(SkillClaim)).all() == []
        assert session.scalars(select(ExperienceProjectDraft)).all() == []
        events = session.scalars(select(ProfileIntakeEvent)).all()
        assert {event.event_type for event in events} == {"message", "validation_error"}


def test_missing_candidate_profile_returns_safe_error(tmp_path: Path) -> None:
    engine = create_sqlite_engine()
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        result = run_profile_intake_extraction(
            ProfileIntakeExtractRequest(latest_user_message="I want to be an Applied AI Engineer."),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    assert result.status_code == 404
    assert result.body["ok"] is False
    assert result.body["code"] == "candidate_profile_not_found"


def make_connector(provider: StaticProvider | RecordingProvider) -> ModelConnector:
    return ModelConnector(
        provider,
        ModelConnectorConfig(
            provider="test",
            routing=ModelRoutingConfig(default_model="mock-default", cheap_model="mock-cheap"),
        ),
    )


def fake_resume_text() -> str:
    return """Resume
Alex Example
Applied AI and platform engineer

Summary
Built production AI, data, and backend systems for customer-facing workflow products.

Experience
Senior Applied AI Engineer | Northstar Systems | 2022 - Present
- Built an LLM evaluation platform for support automation and reduced regression review time.
- Led Python and FastAPI services that processed customer workflow data.
- Partnered with sales, support, and security stakeholders on enterprise rollouts.

Platform Engineer | River Analytics | 2019 - 2022
- Implemented Postgres-backed analytics pipelines and CI/CD deployment workflows.
- Improved observability, tracing, and incident response for data products.
- Mentored engineers on TypeScript, React, API design, and testing.

Software Engineer | Beacon Tools | 2016 - 2019
- Shipped React and Node.js features for developer productivity dashboards.
- Designed auth and audit logging for regulated customer environments.

Projects
Agent Review Console | 2024
RAG Knowledge Base | 2023
Workflow Metrics Dashboard | 2021

Education
State University, B.S. Computer Science

Certifications
AWS Solutions Architect Associate

Skills
Python, TypeScript, JavaScript, React, Next.js, FastAPI, Node.js, Postgres, SQL, RAG, LLM evals,
observability, Docker, Kubernetes, AWS, GCP, Azure, CI/CD, security, product analytics, stakeholder collaboration

Links
https://example.com/profile
https://example.com/project/agent-review
https://example.com/project/rag
"""


def resume_text_without_resume_label() -> str:
    return """Rebekah Love
Louisville, KY | linkedin.com/in/rebekahalove
Applied AI Systems Engineer

PROFESSIONAL SUMMARY
Applied AI Systems Engineer and Founder with 10+ years of experience building production data and AI platforms.

CORE SKILLS
RAG and structured context assembly
LLM evaluation and prompt engineering
Python, FastAPI, PostgreSQL, Docker

PROFESSIONAL EXPERIENCE
Shadow Network Intelligence - Founder & Applied AI Systems Engineer Remote 2024\u2013Present
- Built and deployed a production AI reporting platform.
- Reduced report generation from 8-12 hours to 10-30 minutes.

PROFESSIONAL EXPERIENCE CONTINUED
Sentry Data Systems - Software Developer Remote 2015\u20132018
- Built and optimized large-scale ETL pipelines.

EDUCATION
B.A., Fine Arts - Indiana University

SELECTED TECHNICAL STRENGTHS
Production AI systems, data-intensive platforms, RAG workflows, human review systems
"""


def realistic_resume_output() -> dict[str, object]:
    return profile_update_output(
        assistant_message="I drafted a fuller resume profile and kept every item private for review.",
        draft={
            "targetRoleIntent": {
                "targetTitles": "Applied AI Engineer",
                "targetRoleFamilies": "Applied AI; Platform Engineering",
                "preferredWorkMode": "flexible",
                "domainsOrIndustries": "workflow automation; developer tools",
            },
            "draftFacts": [
                {
                    "claim": f"Resume fact {index}: built or led production AI, data, or platform work.",
                    "category": "resume_evidence",
                    "source": "resume",
                    "status": "needs_review",
                    "visibility": "private",
                    "published": False,
                }
                for index in range(1, 17)
            ],
            "skillClaims": [
                {
                    "skill": f"Resume Skill {index}",
                    "category": "resume_skill",
                    "evidence": f"Used in resume role or project {index}.",
                    "source": "resume",
                    "status": "needs_review",
                    "visibility": "private",
                    "published": False,
                }
                for index in range(1, 29)
            ],
            "experienceAndProjects": [
                {
                    "itemType": "experience",
                    "title": f"Resume Role or Project {index}",
                    "organization": f"Example Organization {index}",
                    "startDate": "2022" if index == 1 else None,
                    "endDate": "Present" if index == 1 else None,
                    "location": "Remote" if index == 1 else None,
                    "summary": f"Delivered applied AI, backend, data, or platform outcomes in resume item {index}.",
                    "bullets": [
                        "Built an LLM evaluation platform for support automation.",
                        "Led Python and FastAPI services that processed workflow data.",
                    ]
                    if index == 1
                    else [],
                    "source": "resume",
                    "status": "needs_review",
                    "visibility": "private",
                    "published": False,
                }
                for index in range(1, 10)
            ],
            "evidenceLinks": [
                {
                    "url": f"https://example.com/resume-evidence/{index}",
                    "label": f"Resume evidence {index}",
                    "source": "resume",
                    "status": "needs_review",
                    "visibility": "private",
                    "published": False,
                }
                for index in range(1, 10)
            ],
        },
        clarifying_questions=[
            "Which two outcomes should be quantified first?",
            "Which resume projects are strongest for applied AI roles?",
            "Which skills should be deemphasized?",
            "Are any links private or outdated?",
        ],
        change_summary=[
            "Extracted representative resume facts.",
            "Created resume-backed skill claims.",
            "Created experience and project drafts.",
            "Added evidence links for review.",
            "Kept all items private and unpublished.",
            "Marked all generated items as needs review.",
        ],
    )


def valid_output() -> dict[str, object]:
    return profile_update_output(
        assistant_message="I drafted updates and kept them private.",
        draft={
        "targetRoleIntent": {
            "targetTitles": "Applied AI Engineer",
        },
        "draftFacts": [],
        "skillClaims": [],
        "experienceAndProjects": [],
        "evidenceLinks": [],
        },
        clarifying_questions=["What production constraints did you handle?"],
        change_summary=["Updated target role intent."],
    )


def unsafe_output() -> dict[str, object]:
    return profile_update_output(
        assistant_message="Bad output.",
        draft={
        "targetRoleIntent": {},
        "draftFacts": [
            {
                "claim": "Unsafe publication attempt.",
                "source": "chat",
                "status": "verified",
                "visibility": "public",
                "published": True,
            }
        ],
        "skillClaims": [],
        "experienceAndProjects": [],
        "evidenceLinks": [],
        },
        clarifying_questions=[],
        change_summary=[],
    )


def valid_output_with_evidence() -> dict[str, object]:
    output = valid_output()
    output["updatedDraftProfile"]["evidenceLinks"] = [
        {
            "url": "https://example.com/jobops",
            "label": "JobOps project",
            "source": "chat",
            "status": "needs_review",
            "visibility": "private",
            "published": False,
        }
    ]
    return output


def profile_basics_output() -> dict[str, object]:
    return profile_update_output(
        assistant_message="I drafted profile basics.",
        draft={
            "profileBasics": {
                "displayName": "Rebekah Love",
                "headline": "Applied AI builder",
                "summary": "Builds pragmatic AI systems for job search workflows.",
                "currentLocation": "Louisville, KY",
            },
            "targetRoleIntent": {},
            "draftFacts": [],
            "skillClaims": [],
            "experienceAndProjects": [],
            "evidenceLinks": [],
        },
        clarifying_questions=[],
        change_summary=["Drafted profile basics."],
    )


def profile_basics_update_output() -> dict[str, object]:
    output = profile_basics_output()
    output["updatedDraftProfile"]["profileBasics"]["headline"] = "AI systems engineer"
    output["changeSummary"] = ["Updated headline."]
    return output


def full_profile_intake_output() -> dict[str, object]:
    return profile_update_output(
        assistant_message="I saved a merged draft.",
        draft={
        "targetRoleIntent": {
            "targetTitles": "Applied AI Engineer",
            "targetRoleFamilies": "Applied AI",
            "preferredWorkMode": "remote",
            "preferredLocations": "New York",
            "domainsOrIndustries": "developer tools",
            "constraints": "No onsite-only roles",
        },
        "draftFacts": [
            {
                "claim": "Built a production FastAPI service for JobOps.",
                "category": "backend",
                "source": "chat",
                "status": "needs_review",
                "visibility": "private",
                "published": False,
            }
        ],
        "skillClaims": [
            {
                "skill": "Python",
                "category": "programming language",
                "evidence": "Used Python and FastAPI in the JobOps backend.",
                "source": "chat",
                "status": "draft",
                "visibility": "private",
                "published": False,
            }
        ],
        "experienceAndProjects": [
            {
                "title": "JobOps",
                "organization": "Independent",
                "summary": "Built the profile intake persistence path.",
                "source": "chat",
                "status": "needs_review",
                "visibility": "private",
                "published": False,
            }
        ],
        "evidenceLinks": [
            {
                "url": "https://example.com/jobops",
                "label": "JobOps project",
                "source": "chat",
                "status": "needs_review",
                "visibility": "private",
                "published": False,
            }
        ],
        },
        clarifying_questions=["What outcomes can we quantify?"],
        change_summary=["Saved initial profile draft."],
    )


def louisville_target_role_output() -> dict[str, object]:
    return profile_update_output(
        assistant_message="I saved your target role direction.",
        draft={
        "targetRoleIntent": {
            "targetTitles": "Applied AI Engineer",
            "targetRoleFamilies": "Applied AI",
            "preferredWorkMode": "flexible",
            "preferredLocations": "Louisville, KY",
            "domainsOrIndustries": "developer tools",
        },
        "draftFacts": [],
        "skillClaims": [],
        "experienceAndProjects": [],
        "evidenceLinks": [],
        },
        clarifying_questions=["What projects best show this direction?"],
        change_summary=["Saved target role intent."],
    )


def london_additive_target_role_output() -> dict[str, object]:
    return profile_update_output(
        assistant_message="I added London while preserving Louisville.",
        draft={
        "targetRoleIntent": {
            "targetTitles": "Applied AI Engineer",
            "targetRoleFamilies": "Applied AI",
            "preferredWorkMode": "flexible",
            "preferredLocations": "Louisville, KY; London, UK",
            "domainsOrIndustries": "developer tools",
        },
        "draftFacts": [],
        "skillClaims": [],
        "experienceAndProjects": [],
        "evidenceLinks": [],
        },
        clarifying_questions=[],
        change_summary=["Added London as a target location."],
    )


def london_replacement_target_role_output() -> dict[str, object]:
    return profile_update_output(
        assistant_message="I changed the target location to London.",
        draft={
        "targetRoleIntent": {
            "preferredLocations": "London, UK",
        },
        "draftFacts": [],
        "skillClaims": [],
        "experienceAndProjects": [],
        "evidenceLinks": [],
        },
        clarifying_questions=[],
        change_summary=["Changed target location to London."],
    )


def london_nyc_sf_final_state_output() -> dict[str, object]:
    return profile_update_output(
        assistant_message="I added NYC and San Francisco Bay as onsite options.",
        draft={
        "targetRoleIntent": {
            "preferredLocations": "London, UK; NYC; San Francisco Bay",
        },
        "draftFacts": [],
        "skillClaims": [],
        "experienceAndProjects": [],
        "evidenceLinks": [],
        },
        clarifying_questions=[],
        change_summary=["Added NYC and San Francisco Bay to preferred locations."],
    )


def additive_role_intent_output() -> dict[str, object]:
    return profile_update_output(
        assistant_message="I added the product AI option.",
        draft={
        "targetRoleIntent": {
            "targetTitles": "Applied AI Engineer; AI Product Engineer",
            "targetRoleFamilies": "Applied AI; AI Product",
            "preferredWorkMode": "flexible",
            "preferredLocations": "Louisville, KY",
            "domainsOrIndustries": "developer tools; healthcare",
        },
        "draftFacts": [],
        "skillClaims": [],
        "experienceAndProjects": [],
        "evidenceLinks": [],
        },
        clarifying_questions=[],
        change_summary=["Added AI Product Engineer and healthcare as target options."],
    )


def empty_patch_output() -> dict[str, object]:
    return profile_update_output(
        assistant_message="I do not have new profile details yet.",
        draft={
        "targetRoleIntent": {
            "targetTitles": "",
            "targetRoleFamilies": "",
            "preferredLocations": "",
            "domainsOrIndustries": "",
            "constraints": "",
        },
        "draftFacts": [],
        "skillClaims": [],
        "experienceAndProjects": [],
        "evidenceLinks": [],
        },
        clarifying_questions=["What else should I add?"],
        change_summary=[],
        no_change_reason="No clear profile update was provided.",
    )


def dedupe_initial_output() -> dict[str, object]:
    output = full_profile_intake_output()
    output["updatedDraftProfile"]["targetRoleIntent"] = {"targetTitles": "Applied AI Engineer"}
    output["updatedDraftProfile"]["skillClaims"] = [
        {
            "skill": "Python",
            "category": "programming language",
            "evidence": "Used Python and FastAPI in the JobOps backend.",
            "source": "chat",
            "status": "draft",
            "visibility": "private",
            "published": False,
        }
    ]
    output["updatedDraftProfile"]["experienceAndProjects"] = [
        {
            "title": "JobOps",
            "organization": None,
            "summary": "Built the profile intake persistence path.",
            "source": "chat",
            "status": "needs_review",
            "visibility": "private",
            "published": False,
        }
    ]
    return output


def dedupe_patch_output() -> dict[str, object]:
    return profile_update_output(
        assistant_message="I added the evals fact.",
        draft={
        "targetRoleIntent": {},
        "draftFacts": [
            {
                "claim": "  built a production fastapi service for jobops.  ",
                "category": "Backend",
                "source": "chat",
                "status": "needs_review",
                "visibility": "private",
                "published": False,
            },
            {
                "claim": "Created LLM regression evals for profile intake.",
                "category": "evals",
                "source": "chat",
                "status": "needs_review",
                "visibility": "private",
                "published": False,
            },
        ],
        "skillClaims": [
            {
                "skill": "python",
                "category": "Programming Language",
                "evidence": "",
                "source": "chat",
                "status": "draft",
                "visibility": "private",
                "published": False,
            }
        ],
        "experienceAndProjects": [
            {
                "title": "jobops",
                "organization": "Independent",
                "summary": "",
                "source": "chat",
                "status": "needs_review",
                "visibility": "private",
                "published": False,
            }
        ],
        "evidenceLinks": [
            {
                "url": "https://example.com/jobops/",
                "label": "",
                "source": "chat",
                "status": "needs_review",
                "visibility": "private",
                "published": False,
            }
        ],
        },
        clarifying_questions=[],
        change_summary=["Added evals fact."],
    )


def profile_update_output(
    *,
    assistant_message: str,
    draft: dict[str, object],
    clarifying_questions: list[str],
    change_summary: list[str],
    no_change_reason: str | None = None,
    removed_items: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "assistantMessage": assistant_message,
        "updatedDraftProfile": {
            "profileBasics": draft.get("profileBasics", {}),
            "targetRoleIntent": draft.get("targetRoleIntent", {}),
            "draftFacts": draft.get("draftFacts", []),
            "skillClaims": draft.get("skillClaims", []),
            "experienceAndProjects": draft.get("experienceAndProjects", []),
            "evidenceLinks": draft.get("evidenceLinks", []),
        },
        "clarifyingQuestions": clarifying_questions,
        "changeSummary": change_summary,
        "noChangeReason": no_change_reason,
        "removedItems": removed_items
        or {
            "draftFactIds": [],
            "skillClaimIds": [],
            "experienceAndProjectIds": [],
            "evidenceLinkIds": [],
            "targetRoleIntentFields": [],
        },
    }


def create_sqlite_engine():
    return create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def make_seeded_session_factory() -> sessionmaker[Session]:
    engine = create_sqlite_engine()
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as session:
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
    return factory


def override_session_dependency(session_factory: sessionmaker[Session]):
    def _override():
        with session_factory() as session:
            yield session

    return _override


def create_auth_session_token(session_factory: sessionmaker[Session]) -> str:
    with session_factory() as session:
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


def seeded_profile(session: Session):
    return seed_public_profile(
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


def make_settings(
    repo_root: Path,
    *,
    gemini_api_key: str | None = None,
    model_provider: str = "mock",
    save_artifacts: bool = False,
    save_raw_text: bool = False,
) -> Settings:
    return Settings(
        app_env="test",
        cheap_model="mock-cheap",
        company_discovery_search_grounding_enabled=True,
        database_url=None,
        default_model="mock-default",
        gemini_api_key=gemini_api_key,
        model_provider=model_provider,
        profile_intake_save_artifacts=save_artifacts,
        profile_intake_save_raw_text=save_raw_text,
        repo_root=repo_root,
    )


def only_run_dir(root: Path) -> Path:
    profile_intake_root = root / "artifacts" / "profile-intake"
    entries = list(profile_intake_root.iterdir())
    assert len(entries) == 1
    return entries[0]
