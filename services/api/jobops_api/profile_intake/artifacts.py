from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from ..model_connector import ModelRequest, ModelResponse
from ..model_artifacts import ArtifactRun, create_artifact_run
from ..settings import Settings
from .prompt import PROFILE_INTAKE_PROMPT_VERSION, PROFILE_INTAKE_SCHEMA_NAME, PROFILE_INTAKE_SCHEMA_VERSION


@dataclass(frozen=True)
class ProfileIntakeInputMetrics:
    latest_user_message_length: int
    existing_draft_fact_count: int
    existing_skill_claim_count: int
    existing_experience_and_project_count: int

    def to_json(self) -> dict[str, int]:
        return {
            "latestUserMessageLength": self.latest_user_message_length,
            "existingDraftFactCount": self.existing_draft_fact_count,
            "existingSkillClaimCount": self.existing_skill_claim_count,
            "existingExperienceAndProjectCount": self.existing_experience_and_project_count,
        }


def create_profile_intake_artifact_run(settings: Settings, run_id: str | None = None) -> ArtifactRun:
    return create_artifact_run(
        artifact_subdirectory="profile-intake",
        enabled=settings.profile_intake_save_artifacts,
        repo_root=settings.repo_root,
        run_id=run_id,
        save_raw_text=settings.profile_intake_save_raw_text,
    )


def build_profile_intake_input_metrics(latest_user_message: str, existing_draft: object) -> ProfileIntakeInputMetrics:
    draft = existing_draft if isinstance(existing_draft, dict) else {}
    return ProfileIntakeInputMetrics(
        latest_user_message_length=len(latest_user_message),
        existing_draft_fact_count=array_length(draft.get("draftFacts")) + array_length(draft.get("facts")),
        existing_skill_claim_count=array_length(draft.get("skillClaims")),
        existing_experience_and_project_count=array_length(draft.get("experienceAndProjects"))
        + array_length(draft.get("experienceSummaries")),
    )


def build_run_metadata(
    *,
    input_metrics: ProfileIntakeInputMetrics,
    latency_ms: int,
    request: ModelRequest,
    response: ModelResponse | None,
    run_id: str,
    status: str,
    validation_issue_count: int,
) -> dict[str, object]:
    return {
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "feature": "profile_intake",
        "input": input_metrics.to_json(),
        "latencyMs": latency_ms,
        "model": response.model if response else request.model,
        "promptVersion": PROFILE_INTAKE_PROMPT_VERSION,
        "provider": response.provider if response else None,
        "responseFinishReason": response.finish_reason if response else None,
        "runId": run_id,
        "schemaName": PROFILE_INTAKE_SCHEMA_NAME,
        "schemaVersion": PROFILE_INTAKE_SCHEMA_VERSION,
        "status": status,
        "task": request.task,
        "validationIssueCount": validation_issue_count,
    }


def array_length(value: object) -> int:
    return len(value) if isinstance(value, list) else 0
