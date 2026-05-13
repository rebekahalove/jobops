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
    ProfileFactDraft,
    ProfileIntakeEvent,
    ProfileIntakeSession,
    SkillClaim,
)
from jobops_api.db.seed_profile import seed_public_profile
from jobops_api.db.session import get_db_session
from jobops_api.model_connector import ModelConnector, ModelConnectorConfig, ModelRequest, ModelResponse, ModelRoutingConfig
from jobops_api.profile_intake.models import ProfileIntakeExtractRequest
from jobops_api.profile_intake.persistence import get_or_create_active_intake_session
from jobops_api.profile_intake.service import run_profile_intake_extraction
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
    monkeypatch.setattr(main_module, "settings", make_settings(tmp_path))
    session_factory = make_seeded_session_factory()
    main_module.app.dependency_overrides[get_db_session] = override_session_dependency(session_factory)
    client = TestClient(main_module.app)

    try:
        response = client.post(
            "/v1/profile-intake/extract",
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
