from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import AuthContext, require_auth_context
from .company_discovery import CompanyDiscoveryRequest, run_company_discovery
from .company_discovery_diagnostics import (
    complete_company_discovery_run,
    fail_company_discovery_run,
    record_company_discovery_provider_call,
    serialize_company_discovery_run_status,
    start_company_discovery_run,
)
from .company_update import CompanyUpdateRequest, run_company_update
from .command_center_guidance import CommandCenterGuidanceRequest, run_command_center_guidance
from .command_router import (
    CommandRouterOutput,
    CommandRouterRequest,
    RouterActionType,
    run_command_router,
)
from .db.models import CandidateProfile, CommandInteractionLog, CompanyDiscoveryRun
from .db.session import create_session_factory, get_db_session
from .job_discovery import JobDiscoveryRequest, run_job_discovery, start_job_discovery_run
from .profile_intake import ProfileIntakeExtractRequest, run_profile_intake_extraction
from .profile_intake.persistence import get_latest_profile_draft_snapshot
from .profiles import get_candidate_profile_by_slug
from .security import require_internal_api_key
from .settings import load_settings


CommandActionType = Literal[
    "add_job_from_url",
    "company_discovery",
    "company_update",
    "job_discovery",
    "discussion_only",
    "career_discovery",
    "profile_guidance",
    "clarifying_questions",
    "suggest_profile_changes_without_applying",
    "follow_company",
    "prioritize_jobs",
    "generate_materials",
    "mark_applied",
    "profile_intake",
    "follow_up_review",
    "unknown",
]

ActionStatus = Literal["planned", "running", "needs_confirmation", "completed", "failed"]
NON_MUTATING_PROFILE_ACTIONS = {
    "discussion_only",
    "career_discovery",
    "profile_guidance",
    "clarifying_questions",
    "suggest_profile_changes_without_applying",
}


router = APIRouter(prefix="/v1/command-center", tags=["command-center"], dependencies=[Depends(require_internal_api_key)])
logger = logging.getLogger(__name__)
COMMAND_FALLBACK_REPLAY_WINDOW = timedelta(minutes=5)


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


class CommandCenterStatusUpdate(ApiModel):
    stage: str
    message: str
    action_type: CommandActionType | None = Field(default=None, alias="actionType")
    confidence: str | None = None
    target_workspace: str | None = Field(default=None, alias="targetWorkspace")


class CommandCenterCommandResponse(ApiModel):
    assistant_message: str
    actions: list[CommandCenterActionResult]
    target_workspace: str | None = None
    result_payload: dict[str, Any] | None = None
    status_updates: list[CommandCenterStatusUpdate] = Field(default_factory=list, alias="statusUpdates")


@router.post("/commands", response_model=CommandCenterCommandResponse)
def execute_command_center_command(
    request: CommandCenterCommandRequest,
    background_tasks: BackgroundTasks = None,
    session: Session = Depends(get_db_session),
    auth: AuthContext = Depends(require_auth_context),
) -> CommandCenterCommandResponse:
    started_at = time.perf_counter()
    settings = load_settings()
    has_auth_context = isinstance(auth, AuthContext)
    candidate_slug = auth.candidate_profile.slug if has_auth_context else meaningful_text(request.candidate_profile_slug)
    candidate_profile = auth.candidate_profile if has_auth_context else resolve_direct_candidate_profile(session, candidate_slug)
    candidate_slug = candidate_slug or (candidate_profile.slug if candidate_profile is not None else None)
    safety_response = preflight_safety_response(request.command)
    if safety_response is not None:
        save_command_interaction_log(
            session,
            auth=auth if has_auth_context else None,
            request=request,
            response=safety_response,
            router_payload=None,
            router_decision=None,
            latency_ms=round((time.perf_counter() - started_at) * 1000),
            model_provider=settings.model_provider,
        )
        session.commit()
        return safety_response
    replay_response = recent_mutating_command_response(session, auth=auth if has_auth_context else None, request=request)
    if replay_response is not None:
        logger.warning(
            "Command-center duplicate fallback replay suppressed: %s",
            json.dumps(
                {
                    "actionTypes": [action.type for action in replay_response.actions],
                    "candidateSlug": candidate_slug,
                    "commandLength": len(request.command),
                    "targetWorkspace": replay_response.target_workspace,
                },
                sort_keys=True,
            ),
        )
        return replay_response
    router_result = run_command_router(
        CommandRouterRequest(
            latest_user_message=request.command,
            active_workspace=request.active_workspace,
            candidate_profile=candidate_profile,
        ),
        db_session=session,
        settings=settings,
    )
    try:
        if router_result.decision is not None and router_result.decision.confidence == "high" and router_result.decision.action_type != "unknown":
            response = dispatch_command_center_action(
                request,
                action_type=router_result.decision.action_type,
                router_decision=router_result.decision,
                router_payload=router_result.body,
                candidate_slug=candidate_slug,
                candidate_profile=candidate_profile,
                session=session,
                settings=settings,
                background_tasks=background_tasks,
            )
        elif router_result.decision is not None:
            response = clarifying_router_response(router_result.decision, router_result.body)
        else:
            interpreted_action = interpret_command(request.command, request.active_workspace)
            if not router_result.unavailable:
                response = CommandCenterCommandResponse(
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
            elif interpreted_action == "company_update":
                response = router_unavailable_company_update_response(router_result.body)
            elif interpreted_action == "unknown" and command_contains_url(request.command):
                response = ambiguous_url_fallback_response(router_result.body)
            elif not should_use_deterministic_fallback(settings, interpreted_action):
                response = CommandCenterCommandResponse(
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
            else:
                response = dispatch_command_center_action(
                    request,
                    action_type=interpreted_action,
                    router_decision=None,
                    router_payload=router_result.body,
                    candidate_slug=candidate_slug,
                    candidate_profile=candidate_profile,
                    session=session,
                    settings=settings,
                    background_tasks=background_tasks,
                )
        response.status_updates = [build_routing_status_update(router_result, response), *response.status_updates]
        save_command_interaction_log(
            session,
            auth=auth if has_auth_context else None,
            request=request,
            response=response,
            router_payload=router_result.body,
            router_decision=router_result.decision,
            latency_ms=round((time.perf_counter() - started_at) * 1000),
            model_provider=settings.model_provider,
        )
        session.commit()
        return response
    except Exception as error:
        save_command_interaction_log(
            session,
            auth=auth if has_auth_context else None,
            request=request,
            response=None,
            router_payload=router_result.body,
            router_decision=router_result.decision,
            latency_ms=round((time.perf_counter() - started_at) * 1000),
            model_provider=settings.model_provider,
            error=error,
        )
        session.commit()
        raise


@router.post("/commands/stream")
def stream_command_center_command(
    request: CommandCenterCommandRequest,
    background_tasks: BackgroundTasks = None,
    session: Session = Depends(get_db_session),
    auth: AuthContext = Depends(require_auth_context),
) -> StreamingResponse:
    def stream_events():
        started_at = time.perf_counter()
        settings = load_settings()
        has_auth_context = isinstance(auth, AuthContext)
        candidate_slug = auth.candidate_profile.slug if has_auth_context else meaningful_text(request.candidate_profile_slug)
        candidate_profile = auth.candidate_profile if has_auth_context else resolve_direct_candidate_profile(session, candidate_slug)
        candidate_slug = candidate_slug or (candidate_profile.slug if candidate_profile is not None else None)
        logger.warning(
            "Command-center stream started: %s",
            json.dumps(
                {
                    "activeWorkspace": request.active_workspace,
                    "candidateSlug": candidate_slug,
                    "commandLength": len(request.command),
                    "hasAuthContext": has_auth_context,
                },
                sort_keys=True,
            ),
        )
        safety_response = preflight_safety_response(request.command)
        if safety_response is not None:
            save_command_interaction_log(
                session,
                auth=auth if has_auth_context else None,
                request=request,
                response=safety_response,
                router_payload=None,
                router_decision=None,
                latency_ms=round((time.perf_counter() - started_at) * 1000),
                model_provider=settings.model_provider,
            )
            session.commit()
            yield command_stream_event("result", {"result": safety_response.model_dump(by_alias=True)})
            return

        router_result = run_command_router(
            CommandRouterRequest(
                latest_user_message=request.command,
                active_workspace=request.active_workspace,
                candidate_profile=candidate_profile,
            ),
            db_session=session,
            settings=settings,
        )
        status_update: CommandCenterStatusUpdate | None = None
        try:
            if router_result.decision is not None:
                status_update = build_router_decision_status_update(router_result.decision)
                logger.warning(
                    "Command-center stream routed: %s",
                    json.dumps(
                        {
                            "actionType": router_result.decision.action_type,
                            "candidateSlug": candidate_slug,
                            "confidence": router_result.decision.confidence,
                            "targetWorkspace": router_result.decision.target_workspace,
                        },
                        sort_keys=True,
                    ),
                )
                yield command_stream_event("status", {"statusUpdate": status_update.model_dump(by_alias=True)})
                if router_result.decision.confidence == "high" and router_result.decision.action_type != "unknown":
                    response = dispatch_command_center_action(
                        request,
                        action_type=router_result.decision.action_type,
                        router_decision=router_result.decision,
                        router_payload=router_result.body,
                        candidate_slug=candidate_slug,
                        candidate_profile=candidate_profile,
                        session=session,
                        settings=settings,
                        background_tasks=background_tasks,
                        defer_company_discovery=True,
                    )
                else:
                    response = clarifying_router_response(router_result.decision, router_result.body)
            else:
                interpreted_action = interpret_command(request.command, request.active_workspace)
                if not router_result.unavailable:
                    response = CommandCenterCommandResponse(
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
                    status_update = build_routing_status_update(router_result, response)
                    yield command_stream_event("status", {"statusUpdate": status_update.model_dump(by_alias=True)})
                elif interpreted_action == "company_update":
                    response = router_unavailable_company_update_response(router_result.body)
                    status_update = build_routing_status_update(router_result, response)
                    yield command_stream_event("status", {"statusUpdate": status_update.model_dump(by_alias=True)})
                elif interpreted_action == "unknown" and command_contains_url(request.command):
                    response = ambiguous_url_fallback_response(router_result.body)
                    status_update = build_routing_status_update(router_result, response)
                    yield command_stream_event("status", {"statusUpdate": status_update.model_dump(by_alias=True)})
                elif not should_use_deterministic_fallback(settings, interpreted_action):
                    response = CommandCenterCommandResponse(
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
                    status_update = build_routing_status_update(router_result, response)
                    yield command_stream_event("status", {"statusUpdate": status_update.model_dump(by_alias=True)})
                else:
                    status_update = CommandCenterStatusUpdate(
                        stage="router",
                        message=(
                            "Status update: the model router was unavailable, so JobOps used the conservative "
                            f"{title_for_action(interpreted_action)} fallback path."
                        ),
                        actionType=interpreted_action,
                        confidence=None,
                        targetWorkspace=target_workspace_for_action(interpreted_action),
                    )
                    yield command_stream_event("status", {"statusUpdate": status_update.model_dump(by_alias=True)})
                    response = dispatch_command_center_action(
                        request,
                        action_type=interpreted_action,
                        router_decision=None,
                        router_payload=router_result.body,
                        candidate_slug=candidate_slug,
                        candidate_profile=candidate_profile,
                        session=session,
                        settings=settings,
                        background_tasks=background_tasks,
                        defer_company_discovery=True,
                    )

            if status_update is None:
                status_update = build_routing_status_update(router_result, response)
            response.status_updates = [status_update, *response.status_updates]
            save_command_interaction_log(
                session,
                auth=auth if has_auth_context else None,
                request=request,
                response=response,
                router_payload=router_result.body,
                router_decision=router_result.decision,
                latency_ms=round((time.perf_counter() - started_at) * 1000),
                model_provider=settings.model_provider,
            )
            session.commit()
            logger.warning(
                "Command-center stream completed: %s",
                json.dumps(
                    {
                        "actionTypes": [action.type for action in response.actions],
                        "candidateSlug": candidate_slug,
                        "latencyMs": round((time.perf_counter() - started_at) * 1000),
                        "status": [action.status for action in response.actions],
                        "targetWorkspace": response.target_workspace,
                    },
                    sort_keys=True,
                ),
            )
            yield command_stream_event("result", {"result": response.model_dump(by_alias=True)})
        except Exception as error:
            logger.exception(
                "Command-center stream failed: %s",
                json.dumps(
                    {
                        "candidateSlug": candidate_slug,
                        "errorType": type(error).__name__,
                        "latencyMs": round((time.perf_counter() - started_at) * 1000),
                        "routerAction": router_result.decision.action_type if router_result.decision is not None else None,
                    },
                    sort_keys=True,
                ),
            )
            error_response = command_stream_failure_response(
                request,
                router_result=router_result,
            )
            try:
                save_command_interaction_log(
                    session,
                    auth=auth if has_auth_context else None,
                    request=request,
                    response=error_response,
                    router_payload=router_result.body,
                    router_decision=router_result.decision,
                    latency_ms=round((time.perf_counter() - started_at) * 1000),
                    model_provider=settings.model_provider,
                    error=error,
                )
                session.commit()
            except Exception:
                session.rollback()
            yield command_stream_event("result", {"result": error_response.model_dump(by_alias=True)})
            return

    return StreamingResponse(stream_events(), media_type="application/x-ndjson")


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
    background_tasks: BackgroundTasks | None = None,
    defer_company_discovery: bool = False,
) -> CommandCenterCommandResponse:
    interpreted_action = normalize_dispatch_action(action_type)

    if interpreted_action in NON_MUTATING_PROFILE_ACTIONS:
        return execute_non_mutating_profile_guidance_command(
            request,
            action_type=interpreted_action,
            router_decision=router_decision,
            router_payload=router_payload,
            candidate_profile=candidate_profile,
            session=session,
            settings=settings,
        )

    if interpreted_action in {"follow_company", "company_discovery"}:
        if candidate_slug is None:
            return missing_candidate_slug_response("company_discovery", "companies", "Discover companies")
        return execute_company_discovery_command(
            request,
            candidate_slug=candidate_slug,
            candidate_profile=candidate_profile,
            session=session,
            settings=settings,
            router_payload=router_payload,
            router_decision=router_decision,
            background_tasks=background_tasks,
            defer_to_background=defer_company_discovery,
        )

    if interpreted_action == "job_discovery":
        if candidate_slug is None:
            return missing_candidate_slug_response(interpreted_action, "jobs", title_for_action(interpreted_action))
        if candidate_profile is None:
            return candidate_profile_not_found_response(interpreted_action, "jobs", title_for_action(interpreted_action))
        return start_async_job_discovery_command(
            request,
            candidate_slug=candidate_slug,
            candidate_profile=candidate_profile,
            session=session,
            router_payload=router_payload,
            router_decision=router_decision,
            background_tasks=background_tasks,
        )

    if interpreted_action == "add_job_from_url":
        if candidate_slug is None:
            return missing_candidate_slug_response(interpreted_action, "jobs", title_for_action(interpreted_action))
        return execute_job_discovery_command(
            request,
            candidate_slug=candidate_slug,
            candidate_profile=candidate_profile,
            session=session,
            settings=settings,
            router_payload=router_payload,
            router_decision=router_decision,
            action_type=interpreted_action,
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
                "I can route profile intake, company discovery, and job discovery from the command center now. "
                "Job URL intake, prioritization, materials, fit scoring, and applied-status updates are still planned tools."
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

    candidate_slug = candidate_slug or meaningful_text(request.candidate_profile_slug)
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
            reconciliation_mode=profile_intake_reconciliation_mode(request.command),
        ),
        db_session=session,
        settings=settings,
        candidate_profile=candidate_profile,
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
        **({"sectionFailures": intake_result.body["sectionFailures"]} if intake_result.body.get("sectionFailures") else {}),
        **router_debug_payload(router_payload),
    }
    assistant_message = profile_draft.get("assistantMessage") or "I updated your profile draft and kept it private for review."
    section_failure_updates = build_profile_section_failure_status_updates(intake_result.body.get("sectionFailures"))

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
        statusUpdates=section_failure_updates,
    )


def missing_candidate_slug_response(
    action_type: CommandActionType,
    target_workspace: str,
    title: str,
) -> CommandCenterCommandResponse:
    error_body = {
        "ok": False,
        "error": (
            "Candidate profile slug is required when no authenticated candidate profile is available."
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


def resolve_direct_candidate_profile(session: Session, candidate_slug: str | None) -> CandidateProfile | None:
    if candidate_slug:
        return get_candidate_profile_by_slug(session, candidate_slug)
    profiles = list(session.scalars(select(CandidateProfile).limit(2)))
    return profiles[0] if len(profiles) == 1 else None


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
    candidate_profile,
    session: Session,
    settings,
    router_payload: dict[str, Any] | None = None,
    router_decision: CommandRouterOutput | None = None,
    background_tasks: BackgroundTasks | None = None,
    defer_to_background: bool = False,
) -> CommandCenterCommandResponse:
    router_action = normalize_dispatch_action(router_decision.action_type) if router_decision is not None else "company_discovery"
    router_confidence = router_decision.confidence if router_decision is not None else None
    target_workspace = (router_decision.target_workspace if router_decision is not None else None) or "companies"
    company_discovery_run = start_company_discovery_run(
        session,
        candidate_profile_id=candidate_profile.id,
        command_text=request.command,
        router_action=router_action,
        router_confidence=router_confidence,
        target_workspace=target_workspace,
    )
    record_company_discovery_provider_call(
        session,
        company_discovery_run_id=company_discovery_run.id,
        stage="router",
        provider="command_router",
        status="completed",
        label="Command router",
        request_summary={
            "activeWorkspace": request.active_workspace or "unknown",
            "commandLength": len(request.command),
        },
        result_summary={
            "actionType": router_action,
            "confidence": router_confidence,
            "targetWorkspace": target_workspace,
        },
    )
    session.commit()
    if defer_to_background and background_tasks is not None:
        background_tasks.add_task(
            run_company_discovery_background,
            company_discovery_run.id,
            candidate_profile.id,
            {
                "latest_user_message": request.command,
                "candidate_profile_slug": candidate_slug,
            },
        )
        serialized_run = serialize_company_discovery_run_status(company_discovery_run)
        result_payload = {
            "ok": True,
            "async": True,
            "companyDiscoveryRunId": company_discovery_run.id,
            "status": company_discovery_run.status if company_discovery_run.status in {"queued", "running", "started"} else "running",
            "companyDiscoveryDiagnostics": serialized_run,
            **router_debug_payload(router_payload),
        }
        return CommandCenterCommandResponse(
            assistant_message="Company discovery started. I will update this card when the saved company results are ready.",
            actions=[
                CommandCenterActionResult(
                    type="company_discovery",
                    status="running",
                    targetWorkspace="companies",
                    title="Discover companies",
                    summary="Company discovery is running. JobOps will refresh Companies when the run completes.",
                    resultPayload=result_payload,
                )
            ],
            target_workspace="companies",
            result_payload=result_payload,
            statusUpdates=[
                CommandCenterStatusUpdate(
                    stage="company_discovery",
                    message="Status update: company discovery started in the background.",
                    actionType="company_discovery",
                    confidence=None,
                    targetWorkspace="companies",
                )
            ],
        )

    discovery_result = run_company_discovery(
        CompanyDiscoveryRequest(
            latest_user_message=request.command,
            candidate_profile_slug=candidate_slug,
        ),
        db_session=session,
        settings=settings,
        candidate_profile=candidate_profile,
        company_discovery_run_id=company_discovery_run.id,
    )
    serialized_run = serialize_company_discovery_run_status(company_discovery_run)

    if discovery_result.status_code != 200 or not discovery_result.body.get("ok"):
        error_message = discovery_result.body.get("error", "Company discovery failed. No companies were saved.")
        result_payload = {
            **discovery_result.body,
            "companyDiscoveryRunId": company_discovery_run.id,
            "companyDiscoveryDiagnostics": serialized_run,
            **router_debug_payload(router_payload),
        }
        return CommandCenterCommandResponse(
            assistant_message=error_message,
            actions=[
                CommandCenterActionResult(
                    type="company_discovery",
                    status="failed",
                    targetWorkspace="companies",
                    title="Discover companies",
                    summary=error_message,
                    resultPayload=result_payload,
                )
            ],
            target_workspace="companies",
            result_payload=result_payload,
        )

    result_payload = {
        **discovery_result.body["result"],
        "companyDiscoveryRunId": company_discovery_run.id,
        "companyDiscoveryDiagnostics": serialized_run,
        **router_debug_payload(router_payload),
    }
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
                summary=(
                    f"Found {added_count} TheirStack company lead{'s' if added_count != 1 else ''}."
                    if result_payload.get("companyEnrichmentPlan")
                    else build_company_discovery_action_summary(added_count)
                ),
                resultPayload=result_payload,
            )
        ],
        target_workspace="companies",
        result_payload=result_payload,
    )


def run_company_discovery_background(
    run_id: str,
    candidate_profile_id: str,
    request_payload: dict[str, Any],
    *,
    session_factory: Callable[[], Session] | None = None,
) -> None:
    factory = session_factory or create_session_factory()
    with factory() as session:
        run = session.get(CompanyDiscoveryRun, run_id)
        candidate_profile = session.get(CandidateProfile, candidate_profile_id)
        if run is None or candidate_profile is None or run.candidate_profile_id != candidate_profile.id:
            return
        settings = load_settings()
        run.status = "running"
        run.started_at = run.started_at or datetime.now(timezone.utc)
        run.error = None
        session.commit()
        logger.warning(
            "Async company discovery run started: %s",
            json.dumps(
                {
                    "candidateProfileId": candidate_profile.id,
                    "runId": run.id,
                    "status": run.status,
                },
                sort_keys=True,
            ),
        )
        try:
            result = run_company_discovery(
                CompanyDiscoveryRequest(**request_payload),
                db_session=session,
                settings=settings,
                candidate_profile=candidate_profile,
                company_discovery_run_id=run.id,
            )
            session.commit()
            refreshed_run = session.get(CompanyDiscoveryRun, run.id)
            if refreshed_run is not None and refreshed_run.status not in {"completed", "failed", "needs_confirmation"}:
                if result.status_code == 200 and result.body.get("ok"):
                    complete_company_discovery_run(session, refreshed_run.id)
                else:
                    fail_company_discovery_run(
                        session,
                        refreshed_run.id,
                        error=str(result.body.get("error") or "Company discovery did not complete."),
                    )
                session.commit()
            logger.warning(
                "Async company discovery run completed: %s",
                json.dumps(
                    {
                        "candidateProfileId": candidate_profile.id,
                        "runId": run.id,
                        "status": session.get(CompanyDiscoveryRun, run.id).status if session.get(CompanyDiscoveryRun, run.id) is not None else None,
                    },
                    sort_keys=True,
                ),
            )
        except Exception as error:
            session.rollback()
            fail_company_discovery_run(
                session,
                run_id,
                error=str(error)[:500] or type(error).__name__,
            )
            session.commit()
            logger.exception(
                "Async company discovery run failed: %s",
                json.dumps(
                    {
                        "candidateProfileId": candidate_profile_id,
                        "errorType": type(error).__name__,
                        "runId": run_id,
                    },
                    sort_keys=True,
                ),
            )


def execute_job_discovery_command(
    request: CommandCenterCommandRequest,
    *,
    candidate_slug: str,
    candidate_profile,
    session: Session,
    settings,
    router_payload: dict[str, Any] | None = None,
    router_decision: CommandRouterOutput | None = None,
    action_type: CommandActionType = "job_discovery",
) -> CommandCenterCommandResponse:
    router_extracted = router_extracted_payload(router_decision, action_type=action_type)
    discovery_result = run_job_discovery(
        JobDiscoveryRequest(
            latest_user_message=request.command,
            candidate_profile_slug=candidate_slug,
            active_workspace=request.active_workspace,
            client_context=request.client_context,
            router_extracted=router_extracted,
        ),
        db_session=session,
        settings=settings,
        candidate_profile=candidate_profile,
    )

    if discovery_result.status_code != 200 or not discovery_result.body.get("ok"):
        error_message = discovery_result.body.get("error", "Job discovery failed. No jobs were saved.")
        return CommandCenterCommandResponse(
            assistant_message=error_message,
            actions=[
                CommandCenterActionResult(
                    type=action_type,
                    status="failed",
                    targetWorkspace="jobs",
                    title=title_for_action(action_type),
                    summary=error_message,
                    resultPayload={**discovery_result.body, **router_debug_payload(router_payload)},
                )
            ],
            target_workspace="jobs",
            result_payload={**discovery_result.body, **router_debug_payload(router_payload)},
        )

    result_payload = {**discovery_result.body["result"], **router_debug_payload(router_payload)}
    saved_count = len(result_payload.get("jobs") or [])
    updated_count = len(result_payload.get("updatedExistingJobs") or [])
    skipped_count = len(result_payload.get("skippedJobs") or [])
    assistant_message = result_payload.get("assistantMessage") or (
        f"Saved {saved_count} job(s) and refreshed {updated_count} existing saved job(s)."
    )

    return CommandCenterCommandResponse(
        assistant_message=assistant_message,
        actions=[
            CommandCenterActionResult(
                type=action_type,
                status="completed",
                targetWorkspace="jobs",
                title=title_for_action(action_type),
                summary=build_job_discovery_action_summary(saved_count, updated_count, skipped_count),
                resultPayload=result_payload,
            )
        ],
        target_workspace="jobs",
        result_payload=result_payload,
        statusUpdates=[
            CommandCenterStatusUpdate(
                stage="job_discovery",
                message="Status update: searched for relevant jobs and reconciled matching postings with your Jobs list.",
                actionType=action_type,
                confidence=None,
                targetWorkspace="jobs",
            )
        ],
    )


def start_async_job_discovery_command(
    request: CommandCenterCommandRequest,
    *,
    candidate_slug: str,
    candidate_profile: CandidateProfile,
    session: Session,
    router_payload: dict[str, Any] | None = None,
    router_decision: CommandRouterOutput | None = None,
    background_tasks: BackgroundTasks | None = None,
) -> CommandCenterCommandResponse:
    router_extracted = router_extracted_payload(router_decision, action_type="job_discovery")
    job_request = JobDiscoveryRequest(
        latest_user_message=request.command,
        candidate_profile_slug=candidate_slug,
        active_workspace=request.active_workspace,
        client_context=request.client_context,
        router_extracted=router_extracted,
    )
    run, created = start_job_discovery_run(
        job_request,
        db_session=session,
        candidate_profile=candidate_profile,
        background_tasks=background_tasks,
    )
    result_payload = {
        "ok": True,
        "async": True,
        "jobSearchRunId": run.id,
        "status": run.status if run.status in {"queued", "running", "started"} else "running",
        "reusedActiveRun": not created,
        "savedCount": run.saved_count,
        "updatedExistingCount": run.updated_existing_count,
        "duplicateCount": run.duplicate_count,
        "skippedCount": run.skipped_count,
        "providerResultCount": run.total_provider_results,
        "modelSelectedCount": run.model_selected_count,
        "providerErrorCount": run.provider_error_count,
    }
    assistant_message = (
        "Job discovery is already running. I will keep tracking that run instead of starting another provider search."
        if not created
        else "Job discovery started. I will update this card when the saved results are ready."
    )
    return CommandCenterCommandResponse(
        assistant_message=assistant_message,
        actions=[
            CommandCenterActionResult(
                type="job_discovery",
                status="running",
                targetWorkspace="jobs",
                title="Discover jobs",
                summary="Job discovery is running. JobOps will refresh Jobs when the run completes.",
                resultPayload=result_payload,
            )
        ],
        target_workspace="jobs",
        result_payload=result_payload,
        statusUpdates=[
            CommandCenterStatusUpdate(
                stage="job_discovery",
                message="Status update: job discovery started in the background.",
                actionType="job_discovery",
                confidence=None,
                targetWorkspace="jobs",
            )
        ],
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


def preflight_safety_response(command: str) -> CommandCenterCommandResponse | None:
    normalized = " ".join(command.casefold().split())
    if any(signal in normalized for signal in ["system prompt", "developer prompt", "hidden prompt", "hidden instructions"]):
        return CommandCenterCommandResponse(
            assistant_message="I cannot reveal hidden system or developer instructions. I can still help with your JobOps workspace data.",
            actions=[
                CommandCenterActionResult(
                    type="unknown",
                    status="needs_confirmation",
                    targetWorkspace=None,
                    title="Review command",
                    summary="No workspace action was executed because the request tried to reveal hidden instructions.",
                )
            ],
        )
    if any(signal in normalized for signal in ["delete", "remove all", "wipe", "drop table", "destroy"]):
        return CommandCenterCommandResponse(
            assistant_message="Destructive actions are disabled for the alpha MVP unless an explicit confirmation flow is added.",
            actions=[
                CommandCenterActionResult(
                    type="unknown",
                    status="needs_confirmation",
                    targetWorkspace=None,
                    title="Review command",
                    summary="No destructive action was executed.",
                )
            ],
        )
    return None


def save_command_interaction_log(
    session: Session,
    *,
    auth: AuthContext | None,
    request: CommandCenterCommandRequest,
    response: CommandCenterCommandResponse | None,
    router_payload: dict[str, Any] | None,
    router_decision: CommandRouterOutput | None,
    latency_ms: int,
    model_provider: str,
    error: Exception | None = None,
) -> None:
    if auth is None:
        return
    actions = response.actions if response is not None else []
    first_action = actions[0] if actions else None
    action_metrics = [safe_action_log_metrics(action) for action in actions]
    command_response = jsonable_encoder(response.model_dump(by_alias=True)) if response is not None else None
    session.add(
        CommandInteractionLog(
            user_id=auth.user_id,
            tenant_id=auth.tenant_id,
            candidate_profile_id=auth.candidate_profile.id,
            user_message=request.command,
            route_selected=(router_decision.action_type if router_decision is not None else first_action.type if first_action else None),
            model_provider=model_provider,
            parsed_action_payload=router_decision.model_dump(by_alias=True) if router_decision is not None else {},
            validation_result={
                "routerOk": bool(router_payload and router_payload.get("ok")),
                "actionStatuses": [action.status for action in actions],
                "actionMetrics": action_metrics,
                "request": {
                    "activeWorkspace": request.active_workspace,
                    "commandLength": len(request.command),
                },
                "commandResponse": command_response,
            },
            action_applied=any(
                action.status in {"completed", "running"} and action.type not in NON_MUTATING_PROFILE_ACTIONS for action in actions
            ),
            final_response=response.assistant_message if response is not None else "",
            error_details={"type": type(error).__name__, "message": str(error)} if error else {},
            latency_ms=latency_ms,
        )
    )


def recent_mutating_command_response(
    session: Session,
    *,
    auth: AuthContext | None,
    request: CommandCenterCommandRequest,
) -> CommandCenterCommandResponse | None:
    if auth is None:
        return None
    replay_since = datetime.now(timezone.utc) - COMMAND_FALLBACK_REPLAY_WINDOW
    recent_logs = session.scalars(
        select(CommandInteractionLog)
        .where(
            CommandInteractionLog.user_id == auth.user_id,
            CommandInteractionLog.tenant_id == auth.tenant_id,
            CommandInteractionLog.candidate_profile_id == auth.candidate_profile.id,
            CommandInteractionLog.user_message == request.command,
            CommandInteractionLog.action_applied.is_(True),
            CommandInteractionLog.created_at >= replay_since,
        )
        .order_by(CommandInteractionLog.created_at.desc())
        .limit(5)
    ).all()
    for log in recent_logs:
        validation_result = log.validation_result if isinstance(log.validation_result, dict) else {}
        logged_request = validation_result.get("request") if isinstance(validation_result.get("request"), dict) else {}
        if logged_request.get("activeWorkspace") != request.active_workspace:
            continue
        command_response = validation_result.get("commandResponse")
        if not isinstance(command_response, dict):
            continue
        try:
            return CommandCenterCommandResponse.model_validate(command_response)
        except Exception:
            continue
    return None


def safe_action_log_metrics(action: CommandCenterActionResult) -> dict[str, Any]:
    payload = action.result_payload if isinstance(action.result_payload, dict) else {}
    metric_keys = [
        "savedCount",
        "updatedExistingCount",
        "skippedJobCount",
        "createdGlobalJobCount",
        "updatedGlobalJobCount",
        "addedCompanyCount",
        "modelJobCount",
        "modelSkippedJobCount",
        "currentSavedJobCount",
        "excludedJobUrlCount",
        "currentSavedCompanyCount",
        "discoveredCount",
        "verifiedCount",
        "duplicateCount",
        "skippedCount",
        "providerResultCount",
        "modelSelectedCount",
        "verifiedUrlCount",
        "savedJobCount",
    ]
    metrics = {key: payload.get(key) for key in metric_keys if isinstance(payload.get(key), int)}
    skipped_reason_counts = payload.get("skippedReasonCounts") or payload.get("skippedReasons")
    if isinstance(skipped_reason_counts, dict):
        metrics["skippedReasons"] = {
            str(reason)[:160]: count
            for reason, count in skipped_reason_counts.items()
            if isinstance(count, int)
        }
    for key in ("jobDiscoveryMode", "providerName", "sourceName"):
        value = payload.get(key)
        if isinstance(value, str):
            metrics[key] = value[:120]
    return {
        "type": action.type,
        "status": action.status,
        "targetWorkspace": action.target_workspace,
        **metrics,
    }


@router.get("/profile-draft/{slug}")
def get_profile_draft(slug: str, session: Session = Depends(get_db_session), auth: AuthContext = Depends(require_auth_context)) -> dict[str, Any]:
    candidate_profile = auth.candidate_profile
    return {
        "ok": True,
        "result": get_latest_profile_draft_snapshot(session, candidate_profile),
    }


def interpret_command(command: str, active_workspace: str | None = None) -> CommandActionType:
    normalized = " ".join(command.lower().split())

    if is_company_update_command(normalized):
        return "company_update"
    if is_company_discovery_command(normalized, active_workspace) and not is_concrete_job_search_command(normalized):
        return "company_discovery"
    if is_job_url_intake_command(normalized):
        return "add_job_from_url"
    if is_job_discovery_command(normalized, active_workspace):
        return "job_discovery"
    if is_profile_discussion_command(normalized):
        return "profile_guidance"
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


def is_profile_discussion_command(normalized_command: str) -> bool:
    if explicit_profile_mutation_signal(normalized_command):
        return False
    signals = [
        "can you help me figure out",
        "help me figure out",
        "what should i emphasize",
        "how should i describe",
        "what roles should i target",
        "which roles should i target",
        "what should my profile say",
        "how should i position",
        "can you suggest profile",
        "suggest profile changes",
    ]
    return any(signal in normalized_command for signal in signals)


def explicit_profile_mutation_signal(normalized_command: str) -> bool:
    return any(
        signal in normalized_command
        for signal in [
            "update my profile",
            "save this",
            "save these",
            "apply this",
            "apply these",
            "add this",
            "add these",
            "put this in my profile",
            "use this to update",
        ]
    )


def is_company_discovery_command(normalized_command: str, active_workspace: str | None) -> bool:
    direct_signals = [
        "follow this company",
        "follow company",
        "watch this company",
        "watch companies",
        "follow companies",
        "companies to follow",
        "companies i should follow",
        "companies that i should follow",
        "companies that i should be following",
        "companies should i follow",
        "companies should i be following",
        "companies to watch",
        "companies i should watch",
        "companies to track",
        "company watchlist",
        "find me companies",
        "find companies",
        "companies hiring",
        "discover companies",
        "company discovery",
        "companies operating",
        "companies in the",
        "companies who hire",
        "companies that hire",
    ]
    if any(signal in normalized_command for signal in direct_signals):
        return True
    if "companies" in normalized_command and "who hire" in normalized_command:
        return True
    if "companies" in normalized_command and "that hire" in normalized_command:
        return True
    if "companies" in normalized_command and "hiring" in normalized_command:
        return True
    if "companies" in normalized_command and any(
        signal in normalized_command for signal in ["follow", "following", "watch", "track", "research"]
    ):
        return True

    if active_workspace == "companies" and any(
        signal in normalized_command
        for signal in ["find", "discover", "follow", "watch", "track", "hire", "hiring"]
    ):
        return True

    return False


def is_concrete_job_search_command(normalized_command: str) -> bool:
    return any(
        signal in normalized_command
        for signal in [
            "find jobs",
            "find me jobs",
            "find some jobs",
            "look for jobs",
            "search for jobs",
            "discover jobs",
            "jobs from my companies",
            "jobs at companies",
            "openings at companies",
            "job openings",
            "job postings",
            "specific jobs",
            "concrete jobs",
        ]
    )


def is_company_update_command(normalized_command: str) -> bool:
    update_signal = any(
        signal in normalized_command
        for signal in ["update", "set", "should be", "add this source", "add this careers", "add this company"]
    )
    field_signal = any(
        signal in normalized_command
        for signal in [
            "job listings url",
            "job listing url",
            "careers url",
            "career url",
            "company url",
            "website",
            "source url",
            "source link",
            "the url for",
            "url for",
            "notes",
            "note",
        ]
    )
    return update_signal and field_signal


def is_job_url_intake_command(normalized_command: str) -> bool:
    return any(
        signal in normalized_command
        for signal in ["add this job", "save this job", "track this role", "job posting", "job url", "add it to my jobs"]
    )


def is_job_discovery_command(normalized_command: str, active_workspace: str | None) -> bool:
    direct_signals = [
        "find me some jobs",
        "find me jobs",
        "find some jobs",
        "find jobs",
        "discover jobs",
        "job discovery",
        "jobs to apply to",
        "jobs that fit my profile",
        "jobs that fit",
        "roles i should consider",
        "show me roles",
        "show me jobs",
        "find remote",
        "find me applied ai",
        "find applied ai",
        "find ai platform",
        "find jobs like this",
        "look for jobs",
        "look for new jobs",
        "check for relevant jobs",
        "check my saved companies for jobs",
        "jobs from my companies list",
        "jobs at companies i follow",
        "jobs at companies i'm following",
        "try something broader",
        "try a broader job search",
        "search again",
    ]
    if any(signal in normalized_command for signal in direct_signals):
        return True
    role_terms = ["role", "roles", "job", "jobs", "posting", "postings", "opening", "openings"]
    find_terms = ["find", "discover", "search", "show me", "recommend"]
    return (
        active_workspace == "jobs"
        and any(signal in normalized_command for signal in find_terms)
        and any(signal in normalized_command for signal in role_terms)
    )


def command_contains_url(command: str) -> bool:
    normalized = command.casefold()
    return "http://" in normalized or "https://" in normalized


def looks_like_future_tool_command(normalized_command: str) -> bool:
    future_tool_signals = [
        "job url",
        "add it to my jobs",
        "find jobs",
        "discover jobs",
        "jobs to apply to",
        "roles i should consider",
        "show me roles",
        "follow company",
        "follow companies",
        "companies to follow",
        "companies i should follow",
        "companies that i should follow",
        "companies that i should be following",
        "companies should i follow",
        "companies should i be following",
        "companies to watch",
        "companies to track",
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
    fact_count = len([item for item in profile_draft.get("draftFacts") or [] if active_profile_draft_item(item)])
    skill_count = len([item for item in profile_draft.get("skillClaims") or [] if active_profile_draft_item(item)])
    experience_count = len(
        [item for item in profile_draft.get("experienceAndProjects") or [] if active_profile_draft_item(item)]
    )
    return (
        f"Updated the saved profile draft with {fact_count} fact(s), {skill_count} skill claim(s), "
        f"and {experience_count} experience/project item(s)."
    )


def execute_non_mutating_profile_guidance_command(
    request: CommandCenterCommandRequest,
    *,
    action_type: CommandActionType,
    router_decision: CommandRouterOutput | None,
    router_payload: dict[str, Any] | None,
    candidate_profile,
    session: Session,
    settings,
) -> CommandCenterCommandResponse:
    guidance_result = run_command_center_guidance(
        CommandCenterGuidanceRequest(
            latestUserMessage=request.command,
            actionType=action_type,
            activeWorkspace=request.active_workspace,
            clientContext=request.client_context,
            routerDecision=router_decision.model_dump(by_alias=True) if router_decision is not None else None,
            routerPayload=router_payload,
        ),
        db_session=session,
        settings=settings,
        candidate_profile=candidate_profile,
    )

    if guidance_result.status_code != 200 or not guidance_result.body.get("ok"):
        error_message = guidance_result.body.get("error", "Guidance failed. No profile data was changed.")
        result_payload = {
            **guidance_result.body,
            "mutated": False,
            **router_debug_payload(router_payload),
        }
        return CommandCenterCommandResponse(
            assistant_message=error_message,
            actions=[
                CommandCenterActionResult(
                    type=action_type,
                    status="failed",
                    targetWorkspace=target_workspace_for_action(action_type),
                    title=title_for_action(action_type),
                    summary="No profile data was changed.",
                    resultPayload=result_payload,
                )
            ],
            target_workspace=target_workspace_for_action(action_type),
            result_payload=result_payload,
        )

    guidance_payload = guidance_result.body.get("result") if isinstance(guidance_result.body.get("result"), dict) else {}
    result_payload = {
        "ok": True,
        "mode": action_type,
        "mutated": False,
        **guidance_payload,
        **router_debug_payload(router_payload),
    }
    return CommandCenterCommandResponse(
        assistant_message=str(guidance_payload.get("assistantMessage") or "I can help think this through without changing saved profile data."),
        actions=[
            CommandCenterActionResult(
                type=action_type,
                status="completed",
                targetWorkspace=target_workspace_for_action(action_type),
                title=title_for_action(action_type),
                summary="Read-only guidance completed. No profile data was changed.",
                resultPayload=result_payload,
            )
        ],
        target_workspace=target_workspace_for_action(action_type),
        result_payload=result_payload,
    )


def profile_intake_reconciliation_mode(command: str) -> str:
    normalized = " ".join(command.casefold().split())
    restore_signals = [
        "restore archived",
        "restore old",
        "restore previous",
        "rebuild from scratch",
        "start from scratch",
        "ignore archived history",
        "ignore archive history",
        "restore everything",
    ]
    return "restore_archived" if any(signal in normalized for signal in restore_signals) else "respect_archived"


def active_profile_draft_item(item: object) -> bool:
    return isinstance(item, dict) and item.get("published") is not True and item.get("status") != "rejected"


def build_profile_section_failure_status_updates(section_failures: object) -> list[CommandCenterStatusUpdate]:
    if not isinstance(section_failures, list) or not section_failures:
        return []
    sections = [
        str(failure.get("section")).replace("_", " ")
        for failure in section_failures
        if isinstance(failure, dict) and failure.get("section")
    ]
    if not sections:
        return []
    return [
        CommandCenterStatusUpdate(
            stage="profile_intake",
            message=(
                "Status update: profile intake skipped "
                f"{', '.join(sections)} after a section extraction error and continued with the remaining sections."
            ),
            actionType="profile_intake",
            confidence=None,
            targetWorkspace="profile",
        )
    ]


def build_company_discovery_action_summary(added_count: int) -> str:
    if added_count == 1:
        return "Saved 1 model-derived company with new review status and verification links."
    return f"Saved {added_count} model-derived companies with new review status and verification links."


def build_job_discovery_action_summary(saved_count: int, updated_count: int, skipped_count: int = 0) -> str:
    if saved_count == 1 and updated_count == 0:
        return "Saved 1 job with a reliable external posting link."
    if saved_count == 0 and updated_count:
        return f"Found {updated_count} existing saved job(s) again and refreshed useful fields."
    if updated_count:
        return f"Saved {saved_count} job(s) and refreshed {updated_count} existing saved job(s)."
    if saved_count == 0 and skipped_count:
        return f"No new jobs were saved; skipped {skipped_count} result(s) without reliable new links."
    if saved_count == 0:
        return "No new jobs were saved."
    return f"Saved {saved_count} job(s) with reliable external posting links."


def build_routing_status_update(
    router_result,
    response: CommandCenterCommandResponse,
) -> CommandCenterStatusUpdate:
    if router_result.decision is not None:
        return build_router_decision_status_update(router_result.decision)

    if router_result.unavailable:
        fallback_action = response.actions[0].type if response.actions else "unknown"
        return CommandCenterStatusUpdate(
            stage="router",
            message=(
                "Status update: the model router was unavailable, so JobOps used the conservative "
                f"{title_for_action(fallback_action)} fallback path."
            ),
            actionType=fallback_action,
            confidence=None,
            targetWorkspace=response.target_workspace,
        )

    fallback_action = response.actions[0].type if response.actions else "unknown"
    return CommandCenterStatusUpdate(
        stage="router",
        message="Status update: the router response was invalid, so no unsafe tool execution was performed.",
        actionType=fallback_action,
        confidence=None,
        targetWorkspace=response.target_workspace,
    )


def build_router_decision_status_update(router_decision: CommandRouterOutput) -> CommandCenterStatusUpdate:
    action_type = normalize_dispatch_action(router_decision.action_type)
    workspace = router_decision.target_workspace or target_workspace_for_action(action_type)
    if action_type in NON_MUTATING_PROFILE_ACTIONS:
        message = "Status update: thinking through guidance without changing saved profile data."
    elif router_decision.confidence == "high" and action_type != "unknown":
        message = (
            f"Status update: routed this command to {title_for_action(action_type)}"
            f" ({action_type}) with high confidence."
        )
    elif action_type == "unknown":
        message = "Status update: the router could not identify a safe workspace for this command yet."
    else:
        message = (
            f"Status update: the router considered {title_for_action(action_type)}"
            f" ({action_type}) but needs confirmation before running it."
        )
    return CommandCenterStatusUpdate(
        stage="router",
        message=message,
        actionType=action_type,
        confidence=router_decision.confidence,
        targetWorkspace=workspace,
    )


def command_stream_event(event_type: str, payload: dict[str, Any]) -> str:
    return json.dumps(jsonable_encoder({"type": event_type, **payload})) + "\n"


def command_stream_failure_response(
    request: CommandCenterCommandRequest,
    *,
    router_result,
) -> CommandCenterCommandResponse:
    action_type = (
        normalize_dispatch_action(router_result.decision.action_type)
        if router_result.decision is not None
        else interpret_command(request.command, request.active_workspace)
    )
    target_workspace = target_workspace_for_action(action_type)
    message = "Command-center failed before completing the routed action. Please try again."
    error_payload = {
        "ok": False,
        "error": message,
        "code": "command_center_stream_failed",
    }
    return CommandCenterCommandResponse(
        assistant_message=message,
        actions=[
            CommandCenterActionResult(
                type=action_type,
                status="failed",
                targetWorkspace=target_workspace,
                title=title_for_action(action_type),
                summary=message,
                resultPayload={**error_payload, **router_debug_payload(router_result.body)},
            )
        ],
        target_workspace=target_workspace,
        result_payload={**error_payload, **router_debug_payload(router_result.body)},
    )


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


def router_unavailable_company_update_response(router_payload: dict[str, Any]) -> CommandCenterCommandResponse:
    message = "Command routing is temporarily unavailable, so I did not update the tracked company. Please try again when the router is available."
    return CommandCenterCommandResponse(
        assistant_message=message,
        actions=[
            CommandCenterActionResult(
                type="company_update",
                status="needs_confirmation",
                targetWorkspace="companies",
                title="Update company",
                summary="No company update was applied because the router was unavailable.",
                resultPayload=router_payload,
            )
        ],
        target_workspace="companies",
        result_payload=router_payload,
    )


def ambiguous_url_fallback_response(router_payload: dict[str, Any]) -> CommandCenterCommandResponse:
    message = "Do you want me to save this as a job posting, or update a tracked company's careers/job listings URL?"
    return CommandCenterCommandResponse(
        assistant_message=message,
        actions=[
            CommandCenterActionResult(
                type="unknown",
                status="needs_confirmation",
                targetWorkspace=None,
                title="Review command",
                summary="The command contains a URL, but the deterministic fallback could not safely choose a tool.",
                resultPayload=router_payload,
            )
        ],
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


def router_extracted_payload(
    router_decision: CommandRouterOutput | None,
    *,
    action_type: CommandActionType,
) -> dict[str, Any] | None:
    payload = router_decision.extracted.model_dump(by_alias=True) if router_decision is not None else {}
    if router_decision is not None:
        payload["commandRouterAction"] = normalize_dispatch_action(router_decision.action_type)
        payload["commandRouterConfidence"] = router_decision.confidence
        payload["commandRouterTargetWorkspace"] = router_decision.target_workspace
    elif action_type:
        payload["commandRouterAction"] = action_type
    return payload or None


def normalize_dispatch_action(action_type: CommandActionType | RouterActionType) -> CommandActionType:
    if action_type == "company_discovery":
        return "company_discovery"
    if action_type == "job_discovery":
        return "job_discovery"
    return action_type


def should_use_deterministic_fallback(settings, action_type: CommandActionType) -> bool:
    if action_type == "profile_intake":
        return True
    if settings.model_provider.strip().lower() == "mock":
        return True
    return action_type not in {"company_discovery", "follow_company", "company_update", "job_discovery"}


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
        "job_discovery": "jobs",
        "discussion_only": None,
        "career_discovery": "profile",
        "profile_guidance": "profile",
        "clarifying_questions": "profile",
        "suggest_profile_changes_without_applying": "profile",
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
        "job_discovery": "Discover jobs",
        "discussion_only": "Discuss",
        "career_discovery": "Explore career direction",
        "profile_guidance": "Profile guidance",
        "clarifying_questions": "Clarify profile direction",
        "suggest_profile_changes_without_applying": "Suggest profile changes",
        "follow_company": "Follow company",
        "prioritize_jobs": "Prioritize saved jobs",
        "generate_materials": "Generate application materials",
        "mark_applied": "Mark job as applied",
        "profile_intake": "Update profile",
        "follow_up_review": "Review follow-ups",
        "unknown": "Review command",
    }[action_type]
from .auth import AuthContext, require_auth_context
