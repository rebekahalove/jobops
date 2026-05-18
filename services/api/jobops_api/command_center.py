from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from .company_discovery import CompanyDiscoveryRequest, run_company_discovery
from .db.session import get_db_session
from .profile_intake import ProfileIntakeExtractRequest, run_profile_intake_extraction
from .profile_intake.persistence import get_latest_profile_draft_snapshot
from .profiles import get_candidate_profile_by_slug
from .security import require_internal_api_key
from .settings import load_settings


CommandActionType = Literal[
    "add_job_from_url",
    "follow_company",
    "prioritize_jobs",
    "generate_materials",
    "mark_applied",
    "profile_intake",
    "follow_up_review",
    "unknown",
]

ActionStatus = Literal["planned", "needs_confirmation", "completed", "failed"]


router = APIRouter(prefix="/v1/command-center", tags=["command-center"], dependencies=[Depends(require_internal_api_key)])


class ApiModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class CommandCenterCommandRequest(ApiModel):
    command: str = Field(min_length=1, max_length=30000)
    candidate_profile_slug: str | None = Field(
        default=None,
        validation_alias=AliasChoices("candidate_profile_slug", "candidateProfileSlug"),
        serialization_alias="candidate_profile_slug",
        max_length=120,
    )
    active_workspace: str | None = Field(
        default=None,
        validation_alias=AliasChoices("active_workspace", "activeWorkspace"),
        serialization_alias="active_workspace",
        max_length=80,
    )
    client_context: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("client_context", "clientContext"),
        serialization_alias="client_context",
    )


class CommandCenterActionResult(ApiModel):
    type: CommandActionType
    status: ActionStatus
    target_workspace: str | None = Field(default=None, alias="targetWorkspace")
    title: str
    summary: str
    result_payload: dict[str, Any] | None = Field(default=None, alias="resultPayload")


class CommandCenterCommandResponse(ApiModel):
    assistant_message: str
    actions: list[CommandCenterActionResult]
    target_workspace: str | None = None
    result_payload: dict[str, Any] | None = None


@router.post("/commands", response_model=CommandCenterCommandResponse)
def execute_command_center_command(
    request: CommandCenterCommandRequest,
    session: Session = Depends(get_db_session),
) -> CommandCenterCommandResponse:
    settings = load_settings()
    candidate_slug = request.candidate_profile_slug or settings.default_candidate_profile_slug
    interpreted_action = interpret_command(request.command, request.active_workspace)

    if interpreted_action == "follow_company":
        return execute_company_discovery_command(
            request,
            candidate_slug=candidate_slug,
            session=session,
            settings=settings,
        )

    if interpreted_action != "profile_intake":
        return CommandCenterCommandResponse(
            assistant_message=(
                "I can route profile intake and company discovery from the command center now. Job URL intake, "
                "prioritization, materials, fit scoring, and applied-status updates are still planned tools."
            ),
            actions=[
                CommandCenterActionResult(
                    type=interpreted_action,
                    status="planned",
                    targetWorkspace=target_workspace_for_action(interpreted_action),
                    title=title_for_action(interpreted_action),
                    summary="This command was classified, but execution is not implemented yet.",
                )
            ],
            target_workspace=target_workspace_for_action(interpreted_action),
        )

    candidate_profile = get_candidate_profile_by_slug(session, candidate_slug)
    if candidate_profile is None:
        error_body = {
            "ok": False,
            "error": "Candidate profile not found.",
            "code": "candidate_profile_not_found",
        }
        return CommandCenterCommandResponse(
            assistant_message=error_body["error"],
            actions=[
                CommandCenterActionResult(
                    type="profile_intake",
                    status="failed",
                    targetWorkspace="profile",
                    title="Update profile",
                    summary=error_body["error"],
                    resultPayload=error_body,
                )
            ],
            target_workspace="profile",
            result_payload=error_body,
        )

    current_draft = get_latest_profile_draft_snapshot(session, candidate_profile)

    intake_result = run_profile_intake_extraction(
        ProfileIntakeExtractRequest(
            latest_user_message=request.command,
            existing_draft=current_draft,
            candidate_profile_slug=candidate_slug,
        ),
        db_session=session,
        settings=settings,
    )

    if intake_result.status_code != 200 or not intake_result.body.get("ok"):
        error_message = intake_result.body.get("error", "Profile intake failed. No draft data was applied.")
        return CommandCenterCommandResponse(
            assistant_message=error_message,
            actions=[
                CommandCenterActionResult(
                    type="profile_intake",
                    status="failed",
                    targetWorkspace="profile",
                    title="Update profile",
                    summary=error_message,
                    resultPayload=intake_result.body,
                )
            ],
            target_workspace="profile",
            result_payload=intake_result.body,
        )

    profile_draft = intake_result.body["result"]
    result_payload = {
        "profileDraft": profile_draft,
        **({"modelRequest": intake_result.body["modelRequest"]} if intake_result.body.get("modelRequest") else {}),
        **({"modelResponse": intake_result.body["modelResponse"]} if intake_result.body.get("modelResponse") else {}),
    }
    assistant_message = profile_draft.get("assistantMessage") or "I updated your profile draft and kept it private for review."

    return CommandCenterCommandResponse(
        assistant_message=assistant_message,
        actions=[
            CommandCenterActionResult(
                type="profile_intake",
                status="completed",
                targetWorkspace="profile",
                title="Update profile",
                summary=build_profile_action_summary(profile_draft),
                resultPayload=result_payload,
            )
        ],
        target_workspace="profile",
        result_payload=result_payload,
    )


def execute_company_discovery_command(
    request: CommandCenterCommandRequest,
    *,
    candidate_slug: str,
    session: Session,
    settings,
) -> CommandCenterCommandResponse:
    discovery_result = run_company_discovery(
        CompanyDiscoveryRequest(
            latest_user_message=request.command,
            candidate_profile_slug=candidate_slug,
        ),
        db_session=session,
        settings=settings,
    )

    if discovery_result.status_code != 200 or not discovery_result.body.get("ok"):
        error_message = discovery_result.body.get("error", "Company discovery failed. No companies were saved.")
        return CommandCenterCommandResponse(
            assistant_message=error_message,
            actions=[
                CommandCenterActionResult(
                    type="follow_company",
                    status="failed",
                    targetWorkspace="companies",
                    title="Discover companies",
                    summary=error_message,
                    resultPayload=discovery_result.body,
                )
            ],
            target_workspace="companies",
            result_payload=discovery_result.body,
        )

    result_payload = discovery_result.body["result"]
    added_count = len(result_payload.get("companies") or [])
    assistant_message = result_payload.get("assistantMessage") or (
        f"Added {added_count} model-derived companies. Please verify them from their source links."
    )

    return CommandCenterCommandResponse(
        assistant_message=assistant_message,
        actions=[
            CommandCenterActionResult(
                type="follow_company",
                status="completed",
                targetWorkspace="companies",
                title="Discover companies",
                summary=build_company_discovery_action_summary(added_count),
                resultPayload=result_payload,
            )
        ],
        target_workspace="companies",
        result_payload=result_payload,
    )


@router.get("/profile-draft/{slug}")
def get_profile_draft(slug: str, session: Session = Depends(get_db_session)) -> dict[str, Any]:
    candidate_profile = get_candidate_profile_by_slug(session, slug)
    if candidate_profile is None:
        return {
            "ok": False,
            "error": "Candidate profile not found.",
            "code": "candidate_profile_not_found",
        }

    return {
        "ok": True,
        "result": get_latest_profile_draft_snapshot(session, candidate_profile),
    }


def interpret_command(command: str, active_workspace: str | None = None) -> CommandActionType:
    normalized = " ".join(command.lower().split())

    if is_profile_intake_command(normalized, active_workspace):
        return "profile_intake"
    if "follow-up" in normalized or "follow up" in normalized:
        return "follow_up_review"
    if "material" in normalized or "cover letter" in normalized or "resume variant" in normalized:
        return "generate_materials"
    if "mark" in normalized and "applied" in normalized:
        return "mark_applied"
    if "prioritize" in normalized or "which jobs" in normalized or "apply to today" in normalized:
        return "prioritize_jobs"
    if is_company_discovery_command(normalized, active_workspace):
        return "follow_company"
    if "http://" in normalized or "https://" in normalized or "job url" in normalized or "add it to my jobs" in normalized:
        return "add_job_from_url"
    return "unknown"


def is_profile_intake_command(normalized_command: str, active_workspace: str | None) -> bool:
    profile_signals = [
        "i want to be",
        "update my profile",
        "add this project",
        "my experience",
        "my skills",
        "resume",
        "work history",
        "employment",
        "projects",
        "education",
        "certifications",
        "linkedin",
        "github",
    ]
    if any(signal in normalized_command for signal in profile_signals):
        return True

    if active_workspace == "profile" and not looks_like_future_tool_command(normalized_command):
        return True

    return False


def is_company_discovery_command(normalized_command: str, active_workspace: str | None) -> bool:
    direct_signals = [
        "follow this company",
        "follow company",
        "watch this company",
        "watch companies",
        "follow companies",
        "find me companies",
        "find companies",
        "discover companies",
        "company discovery",
        "companies operating",
        "companies in the",
        "companies who hire",
        "companies that hire",
    ]
    if any(signal in normalized_command for signal in direct_signals):
        return True

    if active_workspace == "companies" and any(
        signal in normalized_command
        for signal in ["find", "discover", "follow", "watch", "track", "hire", "hiring"]
    ):
        return True

    return False


def looks_like_future_tool_command(normalized_command: str) -> bool:
    future_tool_signals = [
        "job url",
        "add it to my jobs",
        "follow company",
        "follow companies",
        "find companies",
        "discover companies",
        "company discovery",
        "follow this company",
        "prioritize",
        "which jobs",
        "cover letter",
        "material",
        "mark applied",
        "fit score",
        "fit analysis",
    ]
    return any(signal in normalized_command for signal in future_tool_signals) or "http://" in normalized_command or "https://" in normalized_command


def build_profile_action_summary(profile_draft: dict[str, Any]) -> str:
    fact_count = len(profile_draft.get("draftFacts") or [])
    skill_count = len(profile_draft.get("skillClaims") or [])
    experience_count = len(profile_draft.get("experienceAndProjects") or [])
    return (
        f"Updated the saved profile draft with {fact_count} fact(s), {skill_count} skill claim(s), "
        f"and {experience_count} experience/project item(s)."
    )


def build_company_discovery_action_summary(added_count: int) -> str:
    if added_count == 1:
        return "Saved 1 model-derived company with new review status and verification links."
    return f"Saved {added_count} model-derived companies with new review status and verification links."


def target_workspace_for_action(action_type: CommandActionType) -> str | None:
    return {
        "add_job_from_url": "jobs",
        "follow_company": "companies",
        "prioritize_jobs": "jobs",
        "generate_materials": "materials",
        "mark_applied": "applications",
        "profile_intake": "profile",
        "follow_up_review": "follow-ups",
        "unknown": None,
    }[action_type]


def title_for_action(action_type: CommandActionType) -> str:
    return {
        "add_job_from_url": "Add job from URL",
        "follow_company": "Follow company",
        "prioritize_jobs": "Prioritize saved jobs",
        "generate_materials": "Generate application materials",
        "mark_applied": "Mark job as applied",
        "profile_intake": "Update profile",
        "follow_up_review": "Review follow-ups",
        "unknown": "Review command",
    }[action_type]
