from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import jobops_api.main as main_module
from jobops_api.db.models import (
    Base,
    EvidenceArtifact,
    ExperienceProjectDraft,
    ProfileFact,
    ProfileFactDraft,
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
    def __init__(self, texts: list[str], finish_reason: str | None = "stop") -> None:
        self.texts = texts
        self.finish_reason = finish_reason
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        text_index = min(len(self.requests) - 1, len(self.texts) - 1)
        return ModelResponse(
            finish_reason=self.finish_reason,
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
    assert "debug_run_id" not in result.body


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
    assert provider.requests[0].task == "profile_extract"
    assert provider.requests[0].model == "mock-default"
    assert provider.requests[0].messages[0].role == "system"
    assert provider.requests[0].messages[1].role == "user"


def test_api_endpoint_uses_fastapi_profile_intake_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    monkeypatch.setattr(main_module, "settings", make_settings(tmp_path))
    session_factory = make_seeded_session_factory()
    main_module.app.dependency_overrides[get_db_session] = override_session_dependency(session_factory)
    client = TestClient(main_module.app)

    try:
        response = client.post(
            "/v1/profile-intake/extract",
            headers={INTERNAL_API_KEY_HEADER: "test-secret"},
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
    assert second_prompt["update_semantics"]["empty_output_fields_mean"] == "no_change_not_clear"
    assert second_prompt["update_semantics"]["backend_interprets_additive_or_replacement_language"] is False
    assert (
        second_prompt["update_semantics"]["examples"][0]["expected_output_preferredLocations"]
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
        prompt_payload["update_semantics"]["target_role_intent_update_contract"]
        .startswith("Persistence treats non-empty targetRoleIntent fields as final values")
    )


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


def valid_output() -> dict[str, object]:
    return {
        "assistantMessage": "I drafted updates and kept them private.",
        "targetRoleIntent": {
            "targetTitles": "Applied AI Engineer",
        },
        "draftFacts": [],
        "skillClaims": [],
        "experienceAndProjects": [],
        "evidenceLinks": [],
        "clarifyingQuestions": ["What production constraints did you handle?"],
        "changeSummary": ["Updated target role intent."],
    }


def unsafe_output() -> dict[str, object]:
    return {
        "assistantMessage": "Bad output.",
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
        "clarifyingQuestions": [],
        "changeSummary": [],
    }


def valid_output_with_evidence() -> dict[str, object]:
    output = valid_output()
    output["evidenceLinks"] = [
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


def full_profile_intake_output() -> dict[str, object]:
    return {
        "assistantMessage": "I saved a merged draft.",
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
        "clarifyingQuestions": ["What outcomes can we quantify?"],
        "changeSummary": ["Saved initial profile draft."],
    }


def louisville_target_role_output() -> dict[str, object]:
    return {
        "assistantMessage": "I saved your target role direction.",
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
        "clarifyingQuestions": ["What projects best show this direction?"],
        "changeSummary": ["Saved target role intent."],
    }


def london_additive_target_role_output() -> dict[str, object]:
    return {
        "assistantMessage": "I added London while preserving Louisville.",
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
        "clarifyingQuestions": [],
        "changeSummary": ["Added London as a target location."],
    }


def london_replacement_target_role_output() -> dict[str, object]:
    return {
        "assistantMessage": "I changed the target location to London.",
        "targetRoleIntent": {
            "preferredLocations": "London, UK",
        },
        "draftFacts": [],
        "skillClaims": [],
        "experienceAndProjects": [],
        "evidenceLinks": [],
        "clarifyingQuestions": [],
        "changeSummary": ["Changed target location to London."],
    }


def london_nyc_sf_final_state_output() -> dict[str, object]:
    return {
        "assistantMessage": "I added NYC and San Francisco Bay as onsite options.",
        "targetRoleIntent": {
            "preferredLocations": "London, UK; NYC; San Francisco Bay",
        },
        "draftFacts": [],
        "skillClaims": [],
        "experienceAndProjects": [],
        "evidenceLinks": [],
        "clarifyingQuestions": [],
        "changeSummary": ["Added NYC and San Francisco Bay to preferred locations."],
    }


def additive_role_intent_output() -> dict[str, object]:
    return {
        "assistantMessage": "I added the product AI option.",
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
        "clarifyingQuestions": [],
        "changeSummary": ["Added AI Product Engineer and healthcare as target options."],
    }


def empty_patch_output() -> dict[str, object]:
    return {
        "assistantMessage": "I do not have new profile details yet.",
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
        "clarifyingQuestions": ["What else should I add?"],
        "changeSummary": [],
    }


def dedupe_initial_output() -> dict[str, object]:
    output = full_profile_intake_output()
    output["targetRoleIntent"] = {"targetTitles": "Applied AI Engineer"}
    output["skillClaims"] = [
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
    output["experienceAndProjects"] = [
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
    return {
        "assistantMessage": "I added the evals fact.",
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
        "clarifyingQuestions": [],
        "changeSummary": ["Added evals fact."],
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
        database_url=None,
        default_model="mock-default",
        default_candidate_profile_slug="rebekah-love",
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
