from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

import jobops_api.main as main_module
from jobops_api.profile_intake.models import ProfileIntakeExtractRequest
from jobops_api.profile_intake.providers import ModelRequest, ModelResponse
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
        provider=StaticProvider("not json"),
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
        provider=StaticProvider(
            json.dumps(
                {
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
            )
        ),
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
        provider=StaticProvider("not json"),
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


def test_api_endpoint_uses_fastapi_profile_intake_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(main_module, "settings", make_settings(tmp_path))
    client = TestClient(main_module.app)

    response = client.post(
        "/v1/profile-intake/extract",
        json={"latest_user_message": "I want to be an Applied AI Engineer."},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["result"]["targetRoleIntent"]["targetTitles"] == "Applied AI Engineer"


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

