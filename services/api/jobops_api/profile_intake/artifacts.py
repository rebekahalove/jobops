from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from ..settings import Settings
from .prompt import PROFILE_INTAKE_PROMPT_VERSION, PROFILE_INTAKE_SCHEMA_NAME, PROFILE_INTAKE_SCHEMA_VERSION
from .providers import ModelRequest, ModelResponse


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


@dataclass
class ProfileIntakeArtifactRun:
    enabled: bool
    save_raw_text: bool
    run_id: str | None = None
    run_dir: Path | None = None
    artifact_path: str | None = None

    def write_json(self, filename: str, value: object) -> None:
        if not self.enabled or self.run_dir is None:
            return
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / filename).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    def write_raw_text(self, filename: str, value: str) -> None:
        if not self.enabled or not self.save_raw_text or self.run_dir is None:
            return
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / filename).write_text(value, encoding="utf-8")


def create_profile_intake_artifact_run(settings: Settings, run_id: str | None = None) -> ProfileIntakeArtifactRun:
    if not settings.profile_intake_save_artifacts:
        return ProfileIntakeArtifactRun(enabled=False, save_raw_text=settings.profile_intake_save_raw_text)

    created_at = datetime.now(timezone.utc)
    next_run_id = sanitize_path_segment(run_id or uuid4().hex[:8])
    root = settings.repo_root / "artifacts" / "profile-intake"
    run_dir = root / f"{format_timestamp(created_at)}_{next_run_id}"
    artifact_path = str(run_dir.relative_to(settings.repo_root))

    return ProfileIntakeArtifactRun(
        artifact_path=artifact_path,
        enabled=True,
        run_dir=run_dir,
        run_id=next_run_id,
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


def format_timestamp(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%S%fZ")


def sanitize_path_segment(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", value)

