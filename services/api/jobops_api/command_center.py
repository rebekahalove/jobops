from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from .company_discovery import CompanyDiscoveryRequest, run_company_discovery
from .company_update import CompanyUpdateRequest, run_company_update
from .command_router import (
    CommandRouterOutput,
    CommandRouterRequest,
    RouterActionType,
    run_command_router,
)
from .db.session import get_db_session
from .profile_intake import ProfileIntakeExtractRequest, run_profile_intake_extraction
from .profile_intake.persistence import get_latest_profile_draft_snapshot
from .profiles import get_candidate_profile_by_slug
from .security import require_internal_api_key
from .settings import load_settings


CommandActionType = Literal[
    "add_job_from_url",
    "company_discovery",
    "company_update",
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
    candidate_slug = resolve_candidate_slug(request.candidate_profile_slug, settings.default_candidate_profile_slug)
    candidate_profile = get_candidate_profile_by_slug(session, candidate_slug) if candidate_slug else None
    router_result = run_command_router(
        CommandRouterRequest(
            latest_user_message=request.command,
            active_workspace=request.active_workspace,
            candidate_profile=candidate_profile,
        ),
        db_session=session,
        settings=settings,
    )
    if router_result.decision is not None and router_result.decision.confidence == "high" and router_result.decision.action_type != "unknown":
        return dispatch_command_center_action(
            request,
            action_type=router_result.decision.action_type,
            router_decision=router_result.decision,
            router_payload=router_result.body,
            candidate_slug=candidate_slug,
            candidate_profile=candidate_profile,
            session=session,
            settings=settings,
        )
    if router_result.decision is not None:
        return clarifying_router_response(router_result.decision, router_result.body)

    interpreted_action = interpret_command(request.command, request.active_workspace)
    if not router_result.unavailable:
        return CommandCenterCommandResponse(
            assistant_message="I could not safely route that command. Please clarify which workspace or action you want.",
            actions=[
                CommandCenterActionResult(
                    type="unknown",
                    status="needs_confirmation",
                    targetWorkspace=None,
                    title="Review command",
                    summary="The router response could not be validated, so no tool was executed.",
                    resultPayload=router_result.body,
                )
            ],
            result_payload=router_result.body,
        )

    if not should_use_deterministic_fallback(settings, interpreted_action):
        return CommandCenterCommandResponse(
            assistant_message="Command routing is temporarily unavailable, so I did not execute a tool. Please try again after the router is available.",
            actions=[
                CommandCenterActionResult(
                    type=interpreted_action,
                    status="failed",
                    targetWorkspace=target_workspace_for_action(interpreted_action),
                    title=title_for_action(interpreted_action),
                    summary="The model-assisted router was unavailable and this action can change saved data.",
                    resultPayload=router_result.body,
                )
            ],
            target_workspace=target_workspace_for_action(interpreted_action),
            result_payload=router_result.body,
        )

    return dispatch_command_center_action(
        request,
        action_type=interpreted_action,
        router_decision=None,
        router_payload=router_result.body,
        candidate_slug=candidate_slug,
        candidate_profile=candidate_profile,
        session=session,
        settings=settings,
    )


def dispatch_command_center_action(
    request: CommandCenterCommandRequest,
    *,
    action_type: CommandActionType | RouterActionType,
    router_decision: CommandRouterOutput | None,
    router_payload: dict[str, Any] | None,
    candidate_slug: str | None,
    candidate_profile,
    session: Session,
    settings,
) -> CommandCenterCommandResponse:
    interpreted_action = normalize_dispatch_action(action_type)

    if interpreted_action in {"follow_company", "company_discovery"}:
        if candidate_slug is None:
            return missing_candidate_slug_response("company_discovery", "companies", "Discover companies")
        return execute_company_discovery_command(
            request,
            candidate_slug=candidate_slug,
            session=session,
            settings=settings,
            router_payload=router_payload,
        )

    if interpreted_action == "company_update":
        if candidate_slug is None:
            return missing_candidate_slug_response("company_update", "companies", "Update company")
        if candidate_profile is None:
            return candidate_profile_not_found_response("company_update", "companies", "Update company")
        if router_decision is None:
            return CommandCenterCommandResponse(
                assistant_message="I need the router to extract the company update details before changing a company.",
                actions=[
                    CommandCenterActionResult(
                        type="company_update",
                        status="needs_confirmation",
                        targetWorkspace="companies",
                        title="Update company",
                        summary="No company update was applied.",
                        resultPayload=router_payload,
                    )
                ],
                target_workspace="companies",
                result_payload=router_payload,
            )
        return execute_company_update_command(
            router_decision,
            candidate_profile=candidate_profile,
            session=session,
            router_payload=router_payload,
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

    candidate_slug = resolve_candidate_slug(request.candidate_profile_slug, settings.default_candidate_profile_slug)
    if candidate_slug is None:
        return missing_candidate_slug_response("profile_intake", "profile", "Update profile")

    if candidate_profile is None:
        return candidate_profile_not_found_response("profile_intake", "profile", "Update profile")

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
        result_payload = {**intake_result.body, **router_debug_payload(router_payload)}
        return CommandCenterCommandResponse(
            assistant_message=error_message,
            actions=[
                CommandCenterActionResult(
                    type="profile_intake",
                    status="failed",
                    targetWorkspace="profile",
                    title="Update profile",
                    summary=error_message,
                    resultPayload=result_payload,
                )
            ],
            target_workspace="profile",
            result_payload=result_payload,
        )

    profile_draft = intake_result.body["result"]
    result_payload = {
        "profileDraft": profile_draft,
        **({"modelRequest": intake_result.body["modelRequest"]} if intake_result.body.get("modelRequest") else {}),
        **({"modelResponse": intake_result.body["modelResponse"]} if intake_result.body.get("modelResponse") else {}),
        **router_debug_payload(router_payload),
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


def resolve_candidate_slug(request_slug: str | None, default_slug: str | None) -> str | None:
    return meaningful_text(request_slug) or meaningful_text(default_slug)


def missing_candidate_slug_response(
    action_type: CommandActionType,
    target_workspace: str,
    title: str,
) -> CommandCenterCommandResponse:
    error_body = {
        "ok": False,
        "error": (
            "Candidate profile slug is required. Provide candidate_profile_slug in the request or configure "
            "JOBOPS_DEFAULT_CANDIDATE_PROFILE_SLUG."
        ),
        "code": "candidate_profile_slug_required",
    }
    return CommandCenterCommandResponse(
        assistant_message=error_body["error"],
        actions=[
            CommandCenterActionResult(
                type=action_type,
                status="failed",
                targetWorkspace=target_workspace,
                title=title,
                summary=error_body["error"],
                resultPayload=error_body,
            )
        ],
        target_workspace=target_workspace,
        result_payload=error_body,
    )


def candidate_profile_not_found_response(
    action_type: CommandActionType,
    target_workspace: str,
    title: str,
) -> CommandCenterCommandResponse:
    error_body = {
        "ok": False,
        "error": "Candidate profile not found.",
        "code": "candidate_profile_not_found",
    }
    return CommandCenterCommandResponse(
        assistant_message=error_body["error"],
        actions=[
            CommandCenterActionResult(
                type=action_type,
                status="failed",
                targetWorkspace=target_workspace,
                title=title,
                summary=error_body["error"],
                resultPayload=error_body,
            )
        ],
        target_workspace=target_workspace,
        result_payload=error_body,
    )


def execute_company_discovery_command(
    request: CommandCenterCommandRequest,
    *,
    candidate_slug: str,
    session: Session,
    settings,
    router_payload: dict[str, Any] | None = None,
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
                    type="company_discovery",
                    status="failed",
                    targetWorkspace="companies",
                    title="Discover companies",
                    summary=error_message,
                    resultPayload={**discovery_result.body, **router_debug_payload(router_payload)},
                )
            ],
            target_workspace="companies",
            result_payload={**discovery_result.body, **router_debug_payload(router_payload)},
        )

    result_payload = {**discovery_result.body["result"], **router_debug_payload(router_payload)}
    added_count = len(result_payload.get("companies") or [])
    assistant_message = result_payload.get("assistantMessage") or (
        f"Added {added_count} model-derived companies. Please verify them from their source links."
    )

    return CommandCenterCommandResponse(
        assistant_message=assistant_message,
        actions=[
            CommandCenterActionResult(
                type="company_discovery",
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


def execute_company_update_command(
    router_decision: CommandRouterOutput,
    *,
    candidate_profile,
    session: Session,
    router_payload: dict[str, Any] | None = None,
) -> CommandCenterCommandResponse:
    extracted = router_decision.extracted
    update_result = run_company_update(
        CompanyUpdateRequest(
            company_id=extracted.company_id,
            company_name=extracted.company_name,
            field=extracted.field,
            url=extracted.url,
            raw_text=extracted.raw_text,
        ),
        candidate_profile=candidate_profile,
        db_session=session,
    )
    result_payload = {**update_result.body, **router_debug_payload(router_payload)}
    return CommandCenterCommandResponse(
        assistant_message=update_result.assistant_message,
        actions=[
            CommandCenterActionResult(
                type="company_update",
                status=update_result.status,
                targetWorkspace="companies",
                title="Update company",
                summary=company_update_summary(update_result),
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
        return "company_discovery"
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


def company_update_summary(update_result) -> str:
    if update_result.status == "completed":
        result = update_result.body.get("result", {})
        field = result.get("updatedField", "company field") if isinstance(result, dict) else "company field"
        return f"Updated the tracked company's {str(field).replace('_', ' ')}."
    return update_result.assistant_message


def clarifying_router_response(
    router_decision: CommandRouterOutput,
    router_payload: dict[str, Any],
) -> CommandCenterCommandResponse:
    action_type = normalize_dispatch_action(router_decision.action_type)
    question = router_decision.clarifying_question or "I need one more detail before I can safely route that command."
    return CommandCenterCommandResponse(
        assistant_message=question,
        actions=[
            CommandCenterActionResult(
                type=action_type,
                status="needs_confirmation",
                targetWorkspace=router_decision.target_workspace,
                title=title_for_action(action_type),
                summary=router_decision.reason or "No tool was executed because the router confidence was not high.",
                resultPayload=router_payload,
            )
        ],
        target_workspace=router_decision.target_workspace,
        result_payload=router_payload,
    )


def router_debug_payload(router_payload: dict[str, Any] | None) -> dict[str, Any]:
    if not router_payload:
        return {}
    return {
        key: value
        for key, value in {
            "routerDecision": router_payload.get("result"),
            "routerModelRequest": router_payload.get("modelRequest"),
            "routerModelResponse": router_payload.get("modelResponse"),
        }.items()
        if value is not None
    }


def normalize_dispatch_action(action_type: CommandActionType | RouterActionType) -> CommandActionType:
    if action_type == "company_discovery":
        return "company_discovery"
    return action_type


def should_use_deterministic_fallback(settings, action_type: CommandActionType) -> bool:
    if settings.model_provider.strip().lower() == "mock":
        return True
    return action_type not in {"profile_intake", "company_discovery", "follow_company", "company_update"}


def meaningful_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def target_workspace_for_action(action_type: CommandActionType) -> str | None:
    return {
        "add_job_from_url": "jobs",
        "company_discovery": "companies",
        "company_update": "companies",
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
        "company_discovery": "Discover companies",
        "company_update": "Update company",
        "follow_company": "Follow company",
        "prioritize_jobs": "Prioritize saved jobs",
        "generate_materials": "Generate application materials",
        "mark_applied": "Mark job as applied",
        "profile_intake": "Update profile",
        "follow_up_review": "Review follow-ups",
        "unknown": "Review command",
    }[action_type]
