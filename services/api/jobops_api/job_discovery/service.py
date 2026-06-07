from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..applications import archive_application, restore_application
from ..auth import AuthContext, require_auth_context
from ..company_discovery import (
    build_candidate_target_context,
    discovery_request_allows_broad_results,
    normalize_company_name,
    serialize_current_saved_companies,
    should_prompt_for_discovery_targets,
)
from ..company_canonicalization import (
    CompanyProfileLinkResult,
    clean_company_source_urls,
    domain_from_url,
    ensure_candidate_company_link,
    upsert_canonical_company,
)
from ..db.models import Application, CandidateCompany, CandidateProfile, CandidateSavedJob, JobPosting, JobSearchQueryRun, JobSearchRun
from ..db.session import create_session_factory, get_db_session
from ..model_connector import ModelConnector
from ..profiles import candidate_profile_to_private_context_dict, get_candidate_profile_by_slug
from ..security import require_internal_api_key
from ..settings import Settings, load_settings
from .models import (
    CandidatePoolBuildResult,
    CandidatePoolEntry,
    JobCandidateSelectionResult,
    JobDiscoveryProvider,
    JobDiscoveryRecord,
    JobDiscoveryRequest,
    JobDiscoverySaveResult,
    JobDiscoveryServiceResult,
    JobProviderConfigurationError,
    JobProviderRuntimeError,
    JobSearchRequest,
    JobSearchPlan,
    JobSearchPlannerResult,
    JobUrlVerificationResult,
    LiveJobSourceResult,
    ProviderDiagnostic,
    ProviderSearchOutcome,
    SavedJobActionResponse,
    SavedJobResponse,
    SkippedJobResult,
    SkipReasonCode,
)
from .planning import select_job_search_plan_with_model
from .selection import (
    apply_model_selection_to_source_result,
    build_empty_job_candidate_selection_result,
    select_job_candidates_with_model,
    selected_selection_pairs,
)
from .provider_utils import (
    clean_text_value,
    compact_unique_strings,
    normalize_exclusion_terms,
    normalize_text_for_constraint_matching,
    safe_log_preview,
)
from .url_verification import source_result_verification


JOB_DISCOVERY_SELECTION_CANDIDATE_PREFIX = "J"
ACTIVE_JOB_DISCOVERY_RUN_STATUSES = {"queued", "running", "started"}
TERMINAL_JOB_DISCOVERY_RUN_STATUSES = {"completed", "failed", "cancelled", "needs_confirmation"}
ACTIVE_JOB_DISCOVERY_RUN_STALE_AFTER = timedelta(hours=2)
NO_MODEL_SELECTION_EXPLANATION_FALLBACK = (
    "No model selection explanation was returned; check diagnostics for provider counts and skipped jobs."
)
DEFAULT_SELECTION_ASSISTANT_MESSAGE = "I reviewed the live provider candidates and selected the strongest matches."


router = APIRouter(prefix="/v1", tags=["jobs"], dependencies=[Depends(require_internal_api_key)])
logger = logging.getLogger(__name__)



@router.get("/jobs", response_model=list[SavedJobResponse])
def list_jobs(
    session: Session = Depends(get_db_session),
    auth: AuthContext = Depends(require_auth_context),
) -> list[dict[str, Any]]:
    statement = (
        select(CandidateSavedJob)
        .options(selectinload(CandidateSavedJob.job))
        .where(CandidateSavedJob.candidate_profile_id == auth.candidate_profile.id)
        .order_by(CandidateSavedJob.added_at.desc(), CandidateSavedJob.created_at.desc())
    )
    links = list(session.scalars(statement))
    application_by_job_id = load_application_lookup_for_saved_jobs(session, links, auth.candidate_profile.id)
    return [serialize_saved_job(link, application=application_by_job_id.get(link.job_id)) for link in links]


@router.get("/job-search-runs/{run_id}")
def get_job_search_run_status(
    run_id: str,
    session: Session = Depends(get_db_session),
    auth: AuthContext = Depends(require_auth_context),
) -> dict[str, Any]:
    run = session.scalar(
        select(JobSearchRun).where(
            JobSearchRun.id == run_id,
            JobSearchRun.candidate_profile_id == auth.candidate_profile.id,
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Job search run not found.")
    query_runs = list(
        session.scalars(
            select(JobSearchQueryRun)
            .where(JobSearchQueryRun.job_search_run_id == run.id)
            .order_by(JobSearchQueryRun.created_at.desc())
        )
    )
    payload = serialize_job_search_run_status(run, query_runs)
    log_job_search_run_status_serialized(payload)
    return payload


@router.post("/jobs/{saved_job_id}/archive", response_model=SavedJobActionResponse)
def archive_job(
    saved_job_id: str,
    session: Session = Depends(get_db_session),
    auth: AuthContext = Depends(require_auth_context),
) -> dict[str, Any]:
    saved_job = get_owned_saved_job_or_404(session, saved_job_id, auth.candidate_profile.id)
    application = get_application_for_saved_job(session, saved_job, auth.candidate_profile.id)
    now = datetime.now(timezone.utc)
    job_archived = saved_job.archived_at is None
    if job_archived:
        saved_job.archived_at = now
        saved_job.archived_reason = "Saved job archived by user."
        saved_job.archived_by_action = "user_archived_job"

    application_archived = False
    if application is not None and application.archived_at is None:
        application_archived = archive_application(
            application,
            reason="Application archived with linked saved job.",
            action="user_archived_job",
            archived_at=now,
        )

    session.commit()
    session.refresh(saved_job)
    if application is not None:
        session.refresh(application)

    message = (
        "Job and linked application archived. Saved materials and history were preserved."
        if application_archived
        else "Job archived. Saved materials and history were preserved."
    )
    if not job_archived and not application_archived:
        message = "Job was already archived. Saved materials and history are preserved."
    return saved_job_action_response(
        saved_job,
        application=application,
        job_archived=job_archived,
        application_archived=application_archived,
        message=message,
    )


@router.post("/jobs/{saved_job_id}/restore", response_model=SavedJobActionResponse)
def restore_job(
    saved_job_id: str,
    session: Session = Depends(get_db_session),
    auth: AuthContext = Depends(require_auth_context),
) -> dict[str, Any]:
    saved_job = get_owned_saved_job_or_404(session, saved_job_id, auth.candidate_profile.id)
    application = get_application_for_saved_job(session, saved_job, auth.candidate_profile.id)
    job_restored = saved_job.archived_at is not None
    if job_restored:
        saved_job.archived_at = None
        saved_job.archived_reason = None
        saved_job.archived_by_action = None

    application_restored = False
    application_restore_skipped = False
    if application is not None and application.archived_at is not None:
        if application.archived_by_action == "user_archived_job":
            application_restored = restore_application(application)
        else:
            application_restore_skipped = True

    session.commit()
    session.refresh(saved_job)
    if application is not None:
        session.refresh(application)

    if application_restored:
        message = "Job and linked application restored. Saved materials and history were preserved."
    elif application_restore_skipped:
        message = "Job restored. The linked application stayed archived because it was archived separately."
    elif job_restored:
        message = "Job restored."
    else:
        message = "Job was already active."
    return saved_job_action_response(
        saved_job,
        application=application,
        job_restored=job_restored,
        application_restored=application_restored,
        application_restore_skipped=application_restore_skipped,
        message=message,
    )


@router.post("/jobs/{saved_job_id}/favorite", response_model=SavedJobActionResponse)
def favorite_job(
    saved_job_id: str,
    session: Session = Depends(get_db_session),
    auth: AuthContext = Depends(require_auth_context),
) -> dict[str, Any]:
    saved_job = get_owned_saved_job_or_404(session, saved_job_id, auth.candidate_profile.id)
    application = get_application_for_saved_job(session, saved_job, auth.candidate_profile.id)
    changed = saved_job.status != "saved"
    if changed:
        saved_job.status = "saved"
    session.commit()
    session.refresh(saved_job)
    if application is not None:
        session.refresh(application)
    return saved_job_action_response(
        saved_job,
        application=application,
        message="Job added to Favorites." if changed else "Job was already in Favorites.",
    )


@router.post("/jobs/{saved_job_id}/unfavorite", response_model=SavedJobActionResponse)
def unfavorite_job(
    saved_job_id: str,
    session: Session = Depends(get_db_session),
    auth: AuthContext = Depends(require_auth_context),
) -> dict[str, Any]:
    saved_job = get_owned_saved_job_or_404(session, saved_job_id, auth.candidate_profile.id)
    application = get_application_for_saved_job(session, saved_job, auth.candidate_profile.id)
    changed = saved_job.status != "new"
    if changed:
        saved_job.status = "new"
    session.commit()
    session.refresh(saved_job)
    if application is not None:
        session.refresh(application)
    return saved_job_action_response(
        saved_job,
        application=application,
        message="Job moved back to New." if changed else "Job was already in New.",
    )


def run_job_discovery(
    request: JobDiscoveryRequest,
    *,
    connector: ModelConnector | None = None,
    db_session: Session,
    settings: Settings | None = None,
    candidate_profile: CandidateProfile | None = None,
    job_search_run_id: str | None = None,
) -> JobDiscoveryServiceResult:
    active_settings = settings or load_settings()
    candidate_profile = candidate_profile or get_candidate_profile_by_slug(db_session, request.candidate_profile_slug)
    if candidate_profile is None:
        return JobDiscoveryServiceResult(
            body={"ok": False, "error": "Candidate profile not found.", "code": "candidate_profile_not_found"},
            status_code=404,
        )

    current_saved_jobs = serialize_current_saved_jobs(db_session, candidate_profile.id)
    current_saved_companies = serialize_current_saved_companies(db_session, candidate_profile.id)
    target_context = build_candidate_target_context(db_session, candidate_profile)
    private_profile_context = candidate_profile_to_private_context_dict(candidate_profile)
    if should_prompt_for_discovery_targets(
        request.latest_user_message,
        target_context=target_context,
        private_profile_context=private_profile_context,
    ):
        return build_job_discovery_target_prompt_result(current_saved_jobs=current_saved_jobs, current_saved_companies=current_saved_companies)

    return run_live_source_job_discovery(
        request,
        connector=connector,
        db_session=db_session,
        settings=active_settings,
        candidate_profile=candidate_profile,
        current_saved_jobs=current_saved_jobs,
        current_saved_companies=current_saved_companies,
        target_context=target_context,
        private_profile_context=private_profile_context,
        job_search_run_id=job_search_run_id,
    )


def start_job_discovery_run(
    request: JobDiscoveryRequest,
    *,
    db_session: Session,
    candidate_profile: CandidateProfile,
    background_tasks: Any | None,
    session_factory: Callable[[], Session] | None = None,
) -> tuple[JobSearchRun, bool]:
    stale_before = datetime.now(timezone.utc) - ACTIVE_JOB_DISCOVERY_RUN_STALE_AFTER
    stale_active_runs = list(
        db_session.scalars(
            select(JobSearchRun).where(
                JobSearchRun.candidate_profile_id == candidate_profile.id,
                JobSearchRun.status.in_(ACTIVE_JOB_DISCOVERY_RUN_STATUSES),
                JobSearchRun.created_at < stale_before,
            )
        )
    )
    for run in stale_active_runs:
        run.status = "failed"
        run.completed_at = datetime.now(timezone.utc)
        run.error = "Job discovery run became stale before completion."

    active_run = db_session.scalar(
        select(JobSearchRun)
        .where(
            JobSearchRun.candidate_profile_id == candidate_profile.id,
            JobSearchRun.status.in_(ACTIVE_JOB_DISCOVERY_RUN_STATUSES),
            JobSearchRun.created_at >= stale_before,
        )
        .order_by(JobSearchRun.created_at.desc())
    )
    if active_run is not None:
        db_session.commit()
        return active_run, False

    run = JobSearchRun(
        candidate_profile_id=candidate_profile.id,
        command_text=request.latest_user_message,
        search_plan_json={},
        provider_names=[],
        search_mode=None,
        status="queued",
        total_provider_results=0,
        candidate_pool_count=0,
        candidate_count_after_dedupe=0,
        replans_attempted=0,
        model_selected_count=0,
        saved_count=0,
        updated_existing_count=0,
        duplicate_count=0,
        skipped_count=0,
        provider_error_count=0,
    )
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)

    request_payload = {
        "latest_user_message": request.latest_user_message,
        "candidate_profile_slug": request.candidate_profile_slug,
        "active_workspace": request.active_workspace,
        "client_context": request.client_context,
        "router_extracted": request.router_extracted,
    }
    if background_tasks is not None:
        background_tasks.add_task(
            run_job_discovery_background,
            run.id,
            candidate_profile.id,
            request_payload,
            session_factory=session_factory,
        )
    return run, True


def run_job_discovery_background(
    run_id: str,
    candidate_profile_id: str,
    request_payload: dict[str, Any],
    *,
    session_factory: Callable[[], Session] | None = None,
) -> None:
    factory = session_factory or create_session_factory()
    with factory() as session:
        run = session.get(JobSearchRun, run_id)
        candidate_profile = session.get(CandidateProfile, candidate_profile_id)
        if run is None or candidate_profile is None or run.candidate_profile_id != candidate_profile.id:
            return
        settings = load_settings()
        run.status = "running"
        run.started_at = datetime.now(timezone.utc)
        run.error = None
        session.commit()
        logger.warning(
            "Async job discovery run started: %s",
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
            result = run_job_discovery(
                JobDiscoveryRequest(**request_payload),
                db_session=session,
                settings=settings,
                candidate_profile=candidate_profile,
                job_search_run_id=run.id,
            )
            refreshed_run = session.get(JobSearchRun, run.id)
            if refreshed_run is not None and refreshed_run.status not in TERMINAL_JOB_DISCOVERY_RUN_STATUSES:
                if result.status_code == 200 and result.body.get("ok"):
                    complete_job_search_run(refreshed_run, status="completed", provider_diagnostics=[])
                else:
                    complete_job_search_run(
                        refreshed_run,
                        status="failed",
                        provider_diagnostics=[],
                        error=str(result.body.get("error") or "Job discovery did not complete."),
                    )
                session.commit()
            logger.warning(
                "Async job discovery run completed: %s",
                json.dumps(
                    {
                        "candidateProfileId": candidate_profile.id,
                        "runId": run.id,
                        "status": session.get(JobSearchRun, run.id).status if session.get(JobSearchRun, run.id) is not None else None,
                    },
                    sort_keys=True,
                ),
            )
        except Exception as error:
            session.rollback()
            failed_run = session.get(JobSearchRun, run_id)
            if failed_run is not None:
                complete_job_search_run(
                    failed_run,
                    status="failed",
                    provider_diagnostics=[],
                    error=safe_log_preview(str(error), limit=500) or type(error).__name__,
                )
                session.commit()
            logger.exception(
                "Async job discovery run failed: %s",
                json.dumps(
                    {
                        "candidateProfileId": candidate_profile_id,
                        "errorType": type(error).__name__,
                        "runId": run_id,
                    },
                    sort_keys=True,
                ),
            )

def run_live_source_job_discovery(
    request: JobDiscoveryRequest,
    *,
    connector: ModelConnector | None = None,
    db_session: Session,
    settings: Settings,
    candidate_profile: CandidateProfile,
    current_saved_jobs: list[dict[str, Any]],
    current_saved_companies: list[dict[str, Any]],
    target_context: dict[str, Any],
    private_profile_context: dict[str, Any],
    job_search_run_id: str | None = None,
) -> JobDiscoveryServiceResult:
    user_urls = extract_http_urls(request.latest_user_message)
    provider_names = configured_job_provider_names(settings)
    recent_search_history = load_recent_job_search_history(
        db_session,
        candidate_profile.id,
        limit=settings.job_discovery_recent_search_limit,
    )
    planner_result = select_job_search_plan_with_model(
        request,
        connector=connector,
        settings=settings,
        router_extracted=request.router_extracted,
        current_saved_jobs=current_saved_jobs,
        current_saved_companies=current_saved_companies,
        target_context=target_context,
        private_profile_context=private_profile_context,
        recent_search_history=recent_search_history,
        provider_capabilities=build_provider_capabilities(settings, provider_names),
    )
    search_plan = planner_result.plan
    fresh_search_queries, search_request = build_job_search_request_for_plan(
        request,
        search_plan=search_plan,
        current_saved_companies=current_saved_companies,
        target_context=target_context,
        private_profile_context=private_profile_context,
    )
    search_queries_used: list[str] = []
    provider_diagnostics: list[ProviderDiagnostic] = []
    provider_errors: list[str] = []
    replan_reasons: list[str] = []
    replan_queries: list[str] = []
    replan_decision = "not_evaluated"
    replans_attempted = 0
    save_result: JobDiscoverySaveResult | None = None
    search_run = get_existing_job_search_run(db_session, job_search_run_id, candidate_profile.id) if job_search_run_id else None
    if search_run is None:
        search_run = create_job_search_run(
            db_session,
            candidate_profile=candidate_profile,
            command_text=request.latest_user_message,
            search_plan=search_plan,
            provider_names=provider_names,
        )
    else:
        search_run.status = "running"
        search_run.started_at = search_run.started_at or datetime.now(timezone.utc)
        search_run.command_text = request.latest_user_message
        search_run.search_plan_json = search_plan.model_dump(by_alias=True)
        search_run.provider_names = list(provider_names)
        search_run.search_mode = search_plan.search_mode
        db_session.flush()
    log_job_discovery_run_started(
        settings,
        search_run=search_run,
        candidate_profile=candidate_profile,
        provider_names=provider_names,
        search_plan=search_plan,
        current_saved_job_count=len(current_saved_jobs),
        current_saved_company_count=len(current_saved_companies),
    )

    if user_urls:
        source_results, url_diagnostics, url_errors = build_user_url_source_results(
            user_urls,
            search_request=search_request,
        )
        provider_result_count = len(source_results)
        job_discovery_mode = "live_provider"
        provider_names = ("user_url",)
        search_queries_used = fresh_search_queries
        provider_diagnostics = [
            ProviderDiagnostic(
                provider_name="user_url",
                provider_type="broad_search",
                configured=True,
                attempted=True,
                result_count=len(source_results),
                query="user-provided-url",
            )
        ]
        provider_diagnostics.extend(url_diagnostics)
        provider_errors.extend(url_errors)
    elif not provider_names:
        mode = "unavailable"
        payload = {
            "jobDiscoveryMode": mode,
            "configuredProviders": [],
            "searchQueryCount": len(fresh_search_queries),
            "userUrlCount": 0,
        }
        logger.warning(
            "Job discovery live providers are not configured: %s",
            json.dumps(payload, sort_keys=True),
        )
        complete_job_search_run(search_run, status="failed", provider_diagnostics=[], error="No job discovery providers configured.")
        db_session.commit()
        return live_job_discovery_unconfigured_response(
            settings,
            mode=mode,
            provider_names=(),
            search_queries=fresh_search_queries,
        )
    else:
        try:
            providers = resolve_job_discovery_providers(provider_names)
        except JobProviderConfigurationError as error:
            payload = {
                "configuredProviders": list(provider_names),
                "error": safe_log_preview(str(error), limit=240),
            }
            logger.warning(
                "Job discovery provider configuration failed: %s",
                json.dumps(payload, sort_keys=True),
            )
            complete_job_search_run(search_run, status="failed", provider_diagnostics=[], error=str(error))
            db_session.commit()
            return live_job_discovery_unconfigured_response(
                settings,
                mode="unavailable",
                provider_names=provider_names,
                search_queries=fresh_search_queries,
                detail=str(error),
            )
        job_discovery_mode = "mock" if provider_names == ("mock",) else "live_provider"
        merged_source_results: list[LiveJobSourceResult] = []
        provider_result_count = 0
        current_planner_result: JobSearchPlannerResult = planner_result
        while True:
            search_plan = current_planner_result.plan
            fresh_search_queries, search_request = build_job_search_request_for_plan(
                request,
                search_plan=search_plan,
                current_saved_companies=current_saved_companies,
                target_context=target_context,
                private_profile_context=private_profile_context,
            )
            if replans_attempted > 0:
                replan_queries = compact_unique_strings([*replan_queries, *fresh_search_queries], limit=50)
            search_queries_used = compact_unique_strings([*search_queries_used, *fresh_search_queries], limit=50)
            log_job_discovery_provider_plan(
                settings,
                provider_names=provider_names,
                user_url_count=len(user_urls),
                search_queries=fresh_search_queries,
                saved_job_count=len(current_saved_jobs),
                saved_company_count=len(current_saved_companies),
                search_plan=search_plan,
            )
            routed_providers, route_diagnostics = route_job_discovery_providers(providers, search_request)
            provider_diagnostics.extend(route_diagnostics)
            search_outcome = run_configured_job_providers(routed_providers, search_request, settings)
            provider_diagnostics.extend(search_outcome.diagnostics)
            provider_errors.extend(search_outcome.errors)
            if (
                search_outcome.errors
                and not settings.job_discovery_allow_partial_provider_failures
                and not should_tolerate_partial_company_board_errors(search_outcome, search_plan)
            ):
                persist_job_search_query_runs(db_session, search_run, provider_diagnostics)
                complete_job_search_run(
                    search_run,
                    status="failed",
                    provider_diagnostics=provider_diagnostics,
                    error="; ".join(provider_errors[:3]),
                    replans_attempted=replans_attempted,
                )
                db_session.commit()
                log_job_discovery_provider_summary(
                    settings,
                    provider_names=provider_names,
                    diagnostics=provider_diagnostics,
                    provider_result_count=len(search_outcome.results),
                    candidate_count_after_dedupe=0,
                    saved_count=0,
                    skipped_count=0,
                    errors=provider_errors,
                    search_plan=search_plan,
                    level=logging.WARNING,
                )
                return live_job_discovery_provider_error_response(
                    settings,
                    provider_names=provider_names,
                    search_queries=fresh_search_queries,
                    provider_diagnostics=provider_diagnostics,
                    errors=provider_errors,
                )
            provider_result_count += len(search_outcome.results)
            merged_source_results = dedupe_provider_results([*merged_source_results, *search_outcome.results])
            merged_provider_result_count = len(merged_source_results)
            candidate_pool = build_candidate_pool_for_search_plan(
                request,
                source_results=merged_source_results,
                current_saved_jobs=current_saved_jobs,
                search_request=search_request,
                search_queries_used=search_queries_used,
                target_context=target_context,
                private_profile_context=private_profile_context,
                search_plan=search_plan,
                settings=settings,
            )
            replan_reason = job_search_replan_reason(
                provider_diagnostics=provider_diagnostics,
                provider_result_count=merged_provider_result_count,
                candidate_pool=candidate_pool,
                settings=settings,
            )
            replan_decision = job_search_replan_decision(
                replan_reason=replan_reason,
                provider_diagnostics=provider_diagnostics,
                provider_result_count=merged_provider_result_count,
                candidate_pool=candidate_pool,
                search_plan=search_plan,
                settings=settings,
                replans_attempted=replans_attempted,
            )
            if (
                replan_reason is None
                or not search_plan.provider_strategy.allow_replanning
                or settings.job_discovery_search_replan_limit <= 0
                or replans_attempted >= settings.job_discovery_search_replan_limit
            ):
                if replan_decision != "no_replan_needed":
                    log_job_discovery_replanning_skipped(
                        replan_decision,
                        provider_diagnostics=provider_diagnostics,
                        provider_result_count=merged_provider_result_count,
                        candidate_pool=candidate_pool,
                        settings=settings,
                        replans_attempted=replans_attempted,
                    )
                break
            replan_context = build_job_search_replan_context(
                reason=replan_reason,
                prior_search_plan=search_plan,
                search_queries_used=search_queries_used,
                provider_diagnostics=provider_diagnostics,
                provider_result_count=merged_provider_result_count,
                candidate_pool=candidate_pool,
                settings=settings,
                replans_attempted=replans_attempted,
            )
            replan_reasons.append(replan_reason)
            replans_attempted += 1
            logger.log(
                visible_job_discovery_log_level(settings),
                "Job discovery replanning triggered: %s",
                json.dumps(
                    {
                        "reason": replan_reason,
                        "replansAttempted": replans_attempted,
                        "replanLimit": settings.job_discovery_search_replan_limit,
                        "providerResultCount": merged_provider_result_count,
                        "candidatePoolCount": len(candidate_pool.entries),
                        "totalMatchesReported": total_matches_reported(provider_diagnostics),
                    },
                    sort_keys=True,
                ),
            )
            current_planner_result = select_job_search_plan_with_model(
                request,
                connector=connector,
                settings=settings,
                router_extracted=request.router_extracted,
                current_saved_jobs=current_saved_jobs,
                current_saved_companies=current_saved_companies,
                target_context=target_context,
                private_profile_context=private_profile_context,
                recent_search_history=recent_search_history,
                provider_capabilities=build_provider_capabilities(settings, provider_names),
                replan_context=replan_context,
            )
            planner_result = current_planner_result
        source_results = merged_source_results

    selection_result: JobCandidateSelectionResult | None = None
    search_run.search_plan_json = search_plan.model_dump(by_alias=True)
    search_run.search_mode = search_plan.search_mode
    search_run.provider_names = list(provider_names)
    candidate_pool = build_candidate_pool_for_search_plan(
        request,
        source_results=source_results,
        current_saved_jobs=current_saved_jobs,
        search_request=search_request,
        search_queries_used=search_queries_used,
        target_context=target_context,
        private_profile_context=private_profile_context,
        search_plan=search_plan,
        settings=settings,
    )
    if provider_names == ("user_url",):
        preselection_skipped = []
        source_results = dedupe_provider_results(source_results)
    else:
        preselection_skipped = candidate_pool.skipped
        source_results = [entry.result for entry in candidate_pool.entries]

    if save_result is None and provider_names == ("user_url",):
        save_result = save_live_job_source_results(
            db_session,
            candidate_profile=candidate_profile,
            discovery_query=request.latest_user_message,
            source_results=source_results,
            search_queries_used=search_queries_used,
            provider="user_url",
            verify_urls=True,
            user_constraints=search_request.user_constraints,
        )
    elif save_result is None:
        if candidate_pool.entries:
            selection_result_or_error = select_job_candidates_with_model(
                request,
                connector=connector,
                settings=settings,
                candidate_entries=candidate_pool.entries,
                current_saved_jobs=current_saved_jobs,
                current_saved_companies=current_saved_companies,
                target_context=target_context,
                private_profile_context=private_profile_context,
                provider_diagnostics=provider_diagnostics,
                user_constraints=search_request.user_constraints,
                save_limit=settings.job_discovery_save_limit,
                search_plan=search_plan.model_dump(by_alias=True),
                recent_search_summary=recent_search_history[:10],
            )
            if isinstance(selection_result_or_error, JobDiscoveryServiceResult):
                return selection_result_or_error
            selection_result = selection_result_or_error
            selected_results = [
                apply_model_selection_to_source_result(entry.result, selection)
                for entry, selection in selected_selection_pairs(selection_result)
            ]
        else:
            selection_result = build_empty_job_candidate_selection_result(settings)
            selected_results = []
        save_result = save_live_job_source_results(
            db_session,
            candidate_profile=candidate_profile,
            discovery_query=request.latest_user_message,
            source_results=selected_results,
            search_queries_used=search_queries_used,
            provider=",".join(provider_names) if provider_names else job_discovery_mode,
            verify_urls=True,
            user_constraints=search_request.user_constraints,
        )
    db_session.commit()

    saved_jobs = [serialize_saved_job(link) for link in save_result.saved_links]
    updated_saved_jobs = [serialize_saved_job(link) for link in save_result.updated_existing_links]
    all_skipped_results = [*preselection_skipped, *save_result.skipped]
    skipped_jobs = [item.model_dump(by_alias=True) for item in all_skipped_results]
    skipped_counts = skipped_reason_code_counts(all_skipped_results)
    verified_count = sum(
        1
        for link in [*save_result.saved_links, *save_result.updated_existing_links]
        if link.job is not None and link.job.url_verification_status in {"verified", "mock_verified", "provider_unverified"}
    )
    assistant_message = build_selected_job_discovery_assistant_message(
        selection_result,
        save_result,
        source_results,
        all_skipped_results,
    )
    run_diagnostics = build_job_search_run_diagnostics(
        planner_result=planner_result,
        selection_result=selection_result,
        assistant_message=assistant_message,
        replans_attempted=replans_attempted,
        replan_limit=settings.job_discovery_search_replan_limit,
        replanning_status=job_search_replanning_status(
            replans_attempted,
            settings.job_discovery_search_replan_limit,
            replan_reasons,
        ),
        replan_decision=replan_decision,
        replan_reasons=replan_reasons,
        replan_queries=replan_queries,
    )
    result_payload = {
        "assistantMessage": assistant_message,
        "userVisibleSummary": run_diagnostics["userVisibleSummary"],
        "userSummary": run_diagnostics["userSummary"],
        "jobs": saved_jobs,
        "updatedExistingJobs": updated_saved_jobs,
        "discoveredCount": len(source_results),
        "verifiedCount": verified_count,
        "savedCount": len(saved_jobs),
        "updatedExistingCount": len(updated_saved_jobs),
        "createdGlobalJobCount": len(save_result.created_jobs),
        "updatedGlobalJobCount": len(save_result.updated_jobs),
        "duplicateCount": skipped_counts.get("duplicate_for_user", 0) + skipped_counts.get("duplicate_global_job", 0),
        "skippedCount": len(skipped_jobs),
        "skippedJobCount": len(skipped_jobs),
        "skippedJobs": skipped_jobs,
        "skippedReasons": skipped_counts,
        "jobDiscoveryMode": job_discovery_mode,
        "jobSearchRunId": search_run.id,
        "configuredProviders": list(provider_names),
        "providerDiagnostics": [diagnostic.to_dict() for diagnostic in provider_diagnostics],
        "searchPlan": search_plan.model_dump(by_alias=True),
        "searchCriteria": summarize_search_plan(search_plan),
        "recentSearchesUsed": planner_result.recent_searches_used_count,
        "plannerFallbackUsed": planner_result.fallback_used,
        "plannerRationale": clean_user_facing_explanation(search_plan.rationale, limit=900),
        "plannerProvider": planner_result.response_provider,
        "plannerModel": planner_result.response_model,
        "selectionAssistantMessage": selection_assistant_message(selection_result),
        "selectionSkippedCandidateNotes": selection_skipped_candidate_notes(selection_result),
        "selectionClarifyingQuestions": selection_clarifying_questions(selection_result),
        "searchGroundingEnabled": settings.job_discovery_search_grounding_enabled,
        "providerName": ",".join(provider_names) if provider_names else job_discovery_mode,
        "sourceName": ",".join(provider_names) if provider_names else job_discovery_mode,
        "searchQueriesUsed": search_queries_used,
        "providerResultCount": provider_result_count,
        "providerRawResultCount": provider_raw_result_count(provider_diagnostics, provider_result_count),
        "totalMatchesReported": total_matches_reported(provider_diagnostics),
        "pagesAttempted": total_pages_attempted(provider_diagnostics),
        "replansAttempted": replans_attempted,
        "replanLimit": settings.job_discovery_search_replan_limit,
        "replanningStatus": job_search_replanning_status(
            replans_attempted,
            settings.job_discovery_search_replan_limit,
            replan_reasons,
        ),
        "replanningDecision": replan_decision,
        "replanReason": replan_reasons[-1] if replan_reasons else None,
        "replanReasons": replan_reasons,
        "replanQueries": replan_queries,
        "companiesSearched": search_plan.company_names,
        "candidateCountAfterProviderNormalization": candidate_pool.count_after_provider_normalization,
        "candidateCountAfterDedupe": candidate_pool.count_after_dedupe,
        "candidateCountAfterHardExclusionFilter": candidate_pool.count_after_hard_exclusion_filter,
        "candidateCountAfterDiversityCap": candidate_pool.count_after_diversity_cap,
        "candidateCountSentToModel": len(candidate_pool.entries) if selection_result is not None else 0,
        "modelSelectedCount": len(selection_result.selected_entries) if selection_result is not None else len(saved_jobs),
        "selectedCandidateIds": [entry.candidate_id for entry in selection_result.selected_entries] if selection_result is not None else [],
        "invalidSelectedCandidateIds": selection_result.invalid_candidate_ids if selection_result is not None else [],
        "savedJobIds": [job["id"] for job in saved_jobs],
        "trimmedByCompanyCapCount": candidate_pool.trimmed_by_company_cap_count,
        "trimmedByProviderCapCount": candidate_pool.trimmed_by_provider_cap_count,
        "verifiedUrlCount": verified_count,
        "savedJobCount": len(saved_jobs),
        "currentSavedJobCount": len(current_saved_jobs),
        "excludedJobUrlCount": len(current_saved_job_urls(current_saved_jobs)),
        "currentSavedCompanyCount": len(current_saved_companies),
    }
    persist_job_search_query_runs(db_session, search_run, provider_diagnostics, candidate_pool=candidate_pool)
    complete_job_search_run(
        search_run,
        status="completed",
        provider_diagnostics=provider_diagnostics,
        total_provider_results=provider_result_count,
        candidate_pool_count=len(candidate_pool.entries),
        candidate_count_after_dedupe=candidate_pool.count_after_dedupe,
        model_selected_count=len(selection_result.selected_entries) if selection_result is not None else len(saved_jobs),
        saved_count=len(saved_jobs),
        updated_existing_count=len(updated_saved_jobs),
        duplicate_count=result_payload["duplicateCount"],
        skipped_count=len(skipped_jobs),
        replans_attempted=replans_attempted,
        provider_error_count=len(provider_errors),
        run_diagnostics=run_diagnostics,
    )
    db_session.commit()
    summary_level = logging.INFO
    if provider_errors or (provider_names and provider_result_count == 0):
        summary_level = logging.WARNING
    log_job_discovery_run_completed(
        search_run=search_run,
        provider_result_count=provider_result_count,
        candidate_count_after_dedupe=candidate_pool.count_after_dedupe,
        saved_count=len(saved_jobs),
        updated_existing_count=len(updated_saved_jobs),
        skipped_count=len(skipped_jobs),
        provider_error_count=len(provider_errors),
    )
    log_job_discovery_provider_summary(
        settings,
        provider_names=provider_names,
        diagnostics=provider_diagnostics,
        provider_result_count=provider_result_count,
        candidate_count_after_dedupe=len(source_results),
        saved_count=len(saved_jobs),
        skipped_count=len(skipped_jobs),
        errors=provider_errors,
        search_plan=search_plan,
        level=summary_level,
        replans_attempted=replans_attempted,
        replan_limit=settings.job_discovery_search_replan_limit,
        replan_reasons=replan_reasons,
        replan_decision=replan_decision,
    )
    return JobDiscoveryServiceResult(body={"ok": True, "result": result_payload}, status_code=200)


def live_job_discovery_unconfigured_response(
    settings: Settings,
    *,
    mode: str,
    provider_names: tuple[str, ...],
    search_queries: list[str],
    detail: str | None = None,
) -> JobDiscoveryServiceResult:
    provider_name = ",".join(provider_names) if provider_names else "none"
    body = {
        "ok": False,
        "error": "Live job discovery is not configured. No jobs were saved.",
        "code": "live_job_discovery_not_configured",
        "jobDiscoveryMode": mode,
        "configuredProviders": list(provider_names),
        "providerDiagnostics": [],
        "searchGroundingEnabled": settings.job_discovery_search_grounding_enabled,
        "providerName": provider_name,
        "sourceName": provider_name,
        "searchQueriesUsed": search_queries,
        "providerResultCount": 0,
        "candidateCountAfterDedupe": 0,
        "modelSelectedCount": 0,
        "verifiedUrlCount": 0,
        "savedJobCount": 0,
        "skippedReasons": {},
    }
    if detail and settings.app_env.lower() not in {"prod", "production"}:
        body["debugDetail"] = detail
    return JobDiscoveryServiceResult(body=body, status_code=503)


def build_job_discovery_target_prompt_result(
    *,
    current_saved_jobs: list[dict[str, Any]],
    current_saved_companies: list[dict[str, Any]],
) -> JobDiscoveryServiceResult:
    message = (
        "Before I search for jobs, please complete your target details first: target role, "
        "industries/domains, work mode, and any location preferences. If you are undecided, ask for a "
        "broad exploratory job search and I can return untargeted options with that caveat."
    )
    return JobDiscoveryServiceResult(
        body={
            "ok": True,
            "result": {
                "assistantMessage": message,
                "jobs": [],
                "updatedExistingJobs": [],
                "skippedJobs": [],
                "clarifyingQuestions": [
                    "What target role, industry, or kind of organization should I use for job discovery?"
                ],
                "profileTargetsRequired": True,
                "broadDiscoveryAllowed": True,
                "savedCount": 0,
                "updatedExistingCount": 0,
                "duplicateCount": 0,
                "providerResultCount": 0,
                "providerRawResultCount": 0,
                "candidatePoolCount": 0,
                "candidatePoolAfterDedupeCount": 0,
                "candidatePoolAfterFilterCount": 0,
                "candidatePoolAfterDiversityCount": 0,
                "modelSelectedCount": 0,
                "createdGlobalJobCount": 0,
                "updatedGlobalJobCount": 0,
                "addedCompanyCount": 0,
                "currentSavedJobCount": len(current_saved_jobs),
                "currentSavedCompanyCount": len(current_saved_companies),
                "excludedJobUrlCount": 0,
                "jobDiscoveryMode": "target_required",
                "providerDiagnostics": [],
                "providerErrorCount": 0,
            },
        },
        status_code=200,
    )


def live_job_discovery_provider_error_response(
    settings: Settings,
    *,
    provider_names: tuple[str, ...],
    search_queries: list[str],
    provider_diagnostics: list[ProviderDiagnostic],
    errors: list[str],
) -> JobDiscoveryServiceResult:
    return JobDiscoveryServiceResult(
        body={
            "ok": False,
            "error": "Live job discovery provider failed. No jobs were saved.",
            "code": "live_job_discovery_provider_failed",
            "jobDiscoveryMode": "live_provider",
            "configuredProviders": list(provider_names),
            "providerDiagnostics": [diagnostic.to_dict() for diagnostic in provider_diagnostics],
            "searchGroundingEnabled": settings.job_discovery_search_grounding_enabled,
            "providerName": ",".join(provider_names),
            "sourceName": ",".join(provider_names),
            "searchQueriesUsed": search_queries,
            "providerResultCount": 0,
            "candidateCountAfterDedupe": 0,
            "modelSelectedCount": 0,
            "verifiedUrlCount": 0,
            "savedJobCount": 0,
            "skippedReasons": {},
            "providerErrors": errors if settings.app_env.lower() not in {"prod", "production"} else [],
        },
        status_code=502,
    )


def log_job_discovery_provider_plan(
    settings: Settings,
    *,
    provider_names: tuple[str, ...],
    user_url_count: int,
    search_queries: list[str],
    saved_job_count: int,
    saved_company_count: int,
    search_plan: JobSearchPlan | None = None,
) -> None:
    payload: dict[str, Any] = {
        "configuredProviders": list(provider_names),
        "userUrlCount": user_url_count,
        "searchQueryCount": len(search_queries),
        "savedJobCount": saved_job_count,
        "savedCompanyCount": saved_company_count,
    }
    if should_log_job_discovery_debug(settings):
        payload["searchQueryPreviews"] = [safe_log_preview(query, limit=160) for query in search_queries[:5]]
        if search_plan is not None:
            payload["searchCriteria"] = summarize_search_plan(search_plan)
    logger.info("Job discovery provider plan: %s", json.dumps(payload, sort_keys=True))


def log_job_discovery_run_started(
    settings: Settings,
    *,
    search_run: JobSearchRun,
    candidate_profile: CandidateProfile,
    provider_names: tuple[str, ...],
    search_plan: JobSearchPlan,
    current_saved_job_count: int,
    current_saved_company_count: int,
) -> None:
    payload: dict[str, Any] = {
        "candidateProfileId": candidate_profile.id,
        "candidateSlug": candidate_profile.slug,
        "commandLength": len(search_run.command_text or ""),
        "configuredProviders": list(provider_names),
        "currentSavedCompanyCount": current_saved_company_count,
        "currentSavedJobCount": current_saved_job_count,
        "jobSearchRunId": search_run.id,
        "searchMode": search_plan.search_mode,
    }
    if should_log_job_discovery_debug(settings):
        payload["commandPreview"] = safe_log_preview(search_run.command_text, limit=180)
        payload["searchCriteria"] = summarize_search_plan(search_plan)
    logger.warning("Job discovery run started: %s", json.dumps(payload, sort_keys=True, default=str))


def log_job_discovery_run_completed(
    *,
    search_run: JobSearchRun,
    provider_result_count: int,
    candidate_count_after_dedupe: int,
    saved_count: int,
    updated_existing_count: int,
    skipped_count: int,
    provider_error_count: int,
) -> None:
    payload = {
        "candidatePoolCount": search_run.candidate_pool_count,
        "duplicateCount": search_run.duplicate_count,
        "jobSearchRunId": search_run.id,
        "modelSelectedCount": search_run.model_selected_count,
        "providerErrorCount": provider_error_count,
        "providerResultCount": provider_result_count,
        "candidateCountAfterDedupe": candidate_count_after_dedupe,
        "savedCount": saved_count,
        "searchMode": search_run.search_mode,
        "skippedCount": skipped_count,
        "status": search_run.status,
        "updatedExistingCount": updated_existing_count,
    }
    logger.warning("Job discovery run completed: %s", json.dumps(payload, sort_keys=True, default=str))


def log_job_discovery_provider_summary(
    settings: Settings,
    *,
    provider_names: tuple[str, ...],
    diagnostics: list[ProviderDiagnostic],
    provider_result_count: int,
    candidate_count_after_dedupe: int,
    saved_count: int,
    skipped_count: int,
    errors: list[str],
    search_plan: JobSearchPlan | None = None,
    level: int = logging.INFO,
    replans_attempted: int = 0,
    replan_limit: int | None = None,
    replan_reasons: list[str] | None = None,
    replan_decision: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "configuredProviders": list(provider_names),
        "providerResultCount": provider_result_count,
        "candidateCountAfterDedupe": candidate_count_after_dedupe,
        "savedCount": saved_count,
        "skippedCount": skipped_count,
        "replansAttempted": replans_attempted,
        "replanLimit": settings.job_discovery_search_replan_limit if replan_limit is None else replan_limit,
        "saveLimit": settings.job_discovery_save_limit,
        "candidatePoolLimit": settings.job_discovery_candidate_pool_limit,
        "providerDiagnostics": [
            serialize_provider_diagnostic_for_log(settings, diagnostic) for diagnostic in diagnostics
        ],
    }
    if replan_reasons:
        payload["replanReasons"] = replan_reasons
    if replan_decision:
        payload["replanningDecision"] = replan_decision
    if search_plan is not None and should_log_job_discovery_debug(settings):
        payload["searchCriteria"] = summarize_search_plan(search_plan)
    if errors:
        if should_log_job_discovery_debug(settings):
            payload["providerErrors"] = [safe_log_preview(error, limit=240) for error in errors[:8]]
        else:
            payload["providerErrorCount"] = len(errors)
    visible_level = logging.WARNING if level == logging.INFO and should_log_job_discovery_debug(settings) else level
    logger.log(visible_level, "Job discovery provider summary: %s", json.dumps(payload, sort_keys=True, default=str))


def visible_job_discovery_log_level(settings: Settings) -> int:
    return logging.WARNING if should_log_job_discovery_debug(settings) else logging.INFO


def serialize_provider_diagnostic_for_log(settings: Settings, diagnostic: ProviderDiagnostic) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "providerName": diagnostic.provider_name,
        "providerType": diagnostic.provider_type,
        "configured": diagnostic.configured,
        "attempted": diagnostic.attempted,
        "resultCount": diagnostic.result_count,
    }
    if diagnostic.raw_result_count is not None:
        payload["rawResultCount"] = diagnostic.raw_result_count
    if diagnostic.total_matches is not None:
        payload["totalMatches"] = diagnostic.total_matches
    if diagnostic.page is not None:
        payload["page"] = diagnostic.page
    if diagnostic.pages_attempted is not None:
        payload["pagesAttempted"] = diagnostic.pages_attempted
    if diagnostic.search_mode:
        payload["searchMode"] = diagnostic.search_mode
    if diagnostic.board_token:
        payload["boardToken"] = diagnostic.board_token
    if diagnostic.query and should_log_job_discovery_debug(settings):
        payload["queryPreview"] = safe_log_preview(diagnostic.query, limit=160)
    if diagnostic.location:
        payload["location"] = diagnostic.location
    if diagnostic.company_name:
        payload["companyName"] = diagnostic.company_name
    if diagnostic.request_criteria and should_log_job_discovery_debug(settings):
        payload["requestCriteria"] = diagnostic.request_criteria
    if diagnostic.error:
        payload["error"] = (
            safe_log_preview(diagnostic.error, limit=240)
            if should_log_job_discovery_debug(settings)
            else "present"
        )
    return payload


def should_log_job_discovery_debug(settings: Settings) -> bool:
    return settings.app_env.lower() not in {"prod", "production"}


def build_provider_capabilities(settings: Settings, provider_names: tuple[str, ...]) -> dict[str, Any]:
    return {
        "providers": [
            {
                "name": name,
                "type": provider_type_for_name(name),
                "supports_total_matches": name == "adzuna",
                "supports_pagination": name == "adzuna",
                "supports_company_boards": name in {"greenhouse", "ashby"},
            }
            for name in provider_names
        ],
        "limits": {
            "results_per_provider": settings.job_discovery_results_per_provider,
            "candidate_pool_limit": settings.job_discovery_candidate_pool_limit,
            "save_limit": settings.job_discovery_save_limit,
            "max_provider_pages": settings.job_discovery_max_provider_pages,
            "replan_limit": settings.job_discovery_search_replan_limit,
            "company_search_limit": settings.job_discovery_company_search_limit,
        },
    }


def build_job_search_request_for_plan(
    request: JobDiscoveryRequest,
    *,
    search_plan: JobSearchPlan,
    current_saved_companies: list[dict[str, Any]],
    target_context: dict[str, Any],
    private_profile_context: dict[str, Any],
) -> tuple[list[str], JobSearchRequest]:
    search_queries = build_provider_job_search_queries_from_plan(
        request,
        search_plan=search_plan,
        current_saved_companies=current_saved_companies,
        target_context=target_context,
        private_profile_context=private_profile_context,
    )
    return search_queries, JobSearchRequest(
        latest_user_message=request.latest_user_message,
        search_queries=search_queries,
        results_per_provider=search_plan.provider_strategy.requested_result_goal,
        current_saved_companies=current_saved_companies,
        target_context=target_context,
        private_profile_context=private_profile_context,
        user_constraints=compact_unique_strings(
            [
                *infer_user_constraint_terms(request.latest_user_message, target_context, private_profile_context),
                *search_plan.exclude_terms,
            ],
            limit=40,
        ),
        search_plan=search_plan,
        company_names=search_plan.company_names,
        locations=search_plan.locations,
        max_provider_pages=search_plan.provider_strategy.max_provider_pages,
    )


def build_candidate_pool_for_search_plan(
    request: JobDiscoveryRequest,
    *,
    source_results: list[LiveJobSourceResult],
    current_saved_jobs: list[dict[str, Any]],
    search_request: JobSearchRequest,
    search_queries_used: list[str],
    target_context: dict[str, Any],
    private_profile_context: dict[str, Any],
    search_plan: JobSearchPlan,
    settings: Settings,
) -> CandidatePoolBuildResult:
    return build_candidate_pool(
        source_results,
        current_saved_jobs=current_saved_jobs,
        user_constraints=search_request.user_constraints,
        save_limit=settings.job_discovery_save_limit,
        candidate_pool_limit=settings.job_discovery_candidate_pool_limit,
        company_cap=settings.job_discovery_company_candidate_cap,
        relevance_terms=build_job_relevance_terms(
            request.latest_user_message,
            search_queries=search_queries_used,
            target_context=target_context,
            private_profile_context=private_profile_context,
            search_plan=search_plan,
        ),
    )


def job_search_replan_reason(
    *,
    provider_diagnostics: list[ProviderDiagnostic],
    provider_result_count: int,
    candidate_pool: CandidatePoolBuildResult,
    settings: Settings,
) -> str | None:
    total_matches = total_matches_reported(provider_diagnostics)
    raw_result_count = provider_raw_result_count(provider_diagnostics, provider_result_count)
    candidate_pool_target = min(settings.job_discovery_save_limit, settings.job_discovery_candidate_pool_limit)
    if total_matches == 0:
        return "zero_total_matches"
    if provider_result_count == 0:
        return "no_provider_results"
    if len(candidate_pool.entries) < candidate_pool_target:
        if total_matches is None:
            return None
        if total_matches > 0 and raw_result_count >= total_matches:
            return None
        return "insufficient_candidate_pool"
    return None


def job_search_replan_decision(
    *,
    replan_reason: str | None,
    provider_diagnostics: list[ProviderDiagnostic],
    provider_result_count: int,
    candidate_pool: CandidatePoolBuildResult,
    search_plan: JobSearchPlan,
    settings: Settings,
    replans_attempted: int,
) -> str:
    if replan_reason is not None:
        return f"triggered:{replan_reason}"
    if not search_plan.provider_strategy.allow_replanning:
        return "disabled_by_plan"
    if settings.job_discovery_search_replan_limit <= 0:
        return "disabled_by_settings"
    if replans_attempted >= settings.job_discovery_search_replan_limit:
        return "limit_reached"
    total_matches = total_matches_reported(provider_diagnostics)
    raw_result_count = provider_raw_result_count(provider_diagnostics, provider_result_count)
    candidate_pool_target = min(settings.job_discovery_save_limit, settings.job_discovery_candidate_pool_limit)
    if (
        len(candidate_pool.entries) < candidate_pool_target
        and total_matches is not None
        and total_matches > 0
        and raw_result_count >= total_matches
    ):
        return "provider_results_exhausted"
    return "no_replan_needed"


def log_job_discovery_replanning_skipped(
    decision: str,
    *,
    provider_diagnostics: list[ProviderDiagnostic],
    provider_result_count: int,
    candidate_pool: CandidatePoolBuildResult,
    settings: Settings,
    replans_attempted: int,
) -> None:
    logger.log(
        visible_job_discovery_log_level(settings),
        "Job discovery replanning skipped: %s",
        json.dumps(
            {
                "decision": decision,
                "replansAttempted": replans_attempted,
                "replanLimit": settings.job_discovery_search_replan_limit,
                "providerResultCount": provider_result_count,
                "candidatePoolCount": len(candidate_pool.entries),
                "candidatePoolTarget": min(settings.job_discovery_save_limit, settings.job_discovery_candidate_pool_limit),
                "rawResultCount": provider_raw_result_count(provider_diagnostics, provider_result_count),
                "totalMatchesReported": total_matches_reported(provider_diagnostics),
            },
            sort_keys=True,
        ),
    )


def build_job_search_replan_context(
    *,
    reason: str,
    prior_search_plan: JobSearchPlan,
    search_queries_used: list[str],
    provider_diagnostics: list[ProviderDiagnostic],
    provider_result_count: int,
    candidate_pool: CandidatePoolBuildResult,
    settings: Settings,
    replans_attempted: int,
) -> dict[str, Any]:
    diagnostics = provider_diagnostics[-20:]
    total_matches_values = [
        diagnostic.total_matches for diagnostic in diagnostics if diagnostic.total_matches is not None
    ]
    return {
        "reason": reason,
        "attemptNumber": replans_attempted + 1,
        "priorSearchPlan": prior_search_plan.model_dump(by_alias=True),
        "searchQueriesUsed": search_queries_used[-20:],
        "providerDiagnostics": [diagnostic.to_dict() for diagnostic in diagnostics],
        "totalMatchesValues": total_matches_values,
        "totalMatchesReported": total_matches_reported(provider_diagnostics),
        "rawResultCount": provider_raw_result_count(provider_diagnostics, provider_result_count),
        "normalizedResultCount": sum(
            diagnostic.normalized_result_count
            if diagnostic.normalized_result_count is not None
            else diagnostic.result_count
            for diagnostic in provider_diagnostics
        ),
        "providerResultCount": provider_result_count,
        "candidatePoolCount": len(candidate_pool.entries),
        "candidatePoolTarget": min(settings.job_discovery_save_limit, settings.job_discovery_candidate_pool_limit),
    }


def job_search_replanning_status(replans_attempted: int, replan_limit: int, reasons: list[str]) -> str:
    if replans_attempted > 0:
        return "attempted"
    if replan_limit <= 0:
        return "disabled"
    if reasons:
        return "limited"
    return "not_needed"


def provider_type_for_name(provider_name: str) -> str:
    return {
        "adzuna": "broad_search",
        "greenhouse": "ats_board",
        "ashby": "ats_board",
        "mock": "mock",
    }.get(provider_name, "unknown")


def configured_job_provider_names(settings: Settings) -> tuple[str, ...]:
    providers = tuple(compact_unique_strings(list(settings.job_discovery_providers), limit=20))
    if providers:
        return providers
    source = settings.job_discovery_source.strip().lower()
    if source and source not in {"none", "disabled"}:
        return (source,)
    return ("mock",) if settings.model_provider.strip().lower() == "mock" else ()


def resolve_job_discovery_providers(provider_names: tuple[str, ...]) -> list[JobDiscoveryProvider]:
    from .providers.registry import resolve_job_discovery_providers as resolve_from_registry

    return resolve_from_registry(provider_names)


def run_configured_job_providers(
    providers: list[JobDiscoveryProvider],
    request: JobSearchRequest,
    settings: Settings,
) -> ProviderSearchOutcome:
    results: list[LiveJobSourceResult] = []
    diagnostics: list[ProviderDiagnostic] = []
    errors: list[str] = []
    for provider in providers:
        configured = provider.is_configured(settings) or provider_is_configured_for_request(provider, request, settings)
        if not configured:
            if provider.provider_type == "ats_board":
                logger.info(
                    "Job discovery ATS provider skipped without board targets: %s",
                    json.dumps(
                        {
                            "providerName": provider.provider_name,
                            "providerType": provider.provider_type,
                        },
                        sort_keys=True,
                    ),
                )
                diagnostics.append(
                    ProviderDiagnostic(
                        provider_name=provider.provider_name,
                        provider_type=provider.provider_type,
                        configured=False,
                        attempted=False,
                        reason="no_board_targets_available",
                    )
                )
                continue
            message = f"Job discovery provider {provider.provider_name} is not configured."
            logger.warning(
                "Job discovery provider is not configured: %s",
                json.dumps(
                    {
                        "providerName": provider.provider_name,
                        "providerType": provider.provider_type,
                    },
                    sort_keys=True,
                ),
            )
            diagnostics.append(
                ProviderDiagnostic(
                    provider_name=provider.provider_name,
                    provider_type=provider.provider_type,
                    configured=False,
                    attempted=False,
                    error=message,
                )
            )
            errors.append(message)
            continue
        try:
            outcome = provider.search(request, settings)
        except JobProviderRuntimeError as error:
            logger.warning(
                "Job discovery provider request failed: %s",
                json.dumps(
                    {
                        "providerName": provider.provider_name,
                        "providerType": provider.provider_type,
                        "error": safe_log_preview(str(error), limit=240),
                    },
                    sort_keys=True,
                ),
            )
            diagnostics.append(
                ProviderDiagnostic(
                    provider_name=provider.provider_name,
                    provider_type=provider.provider_type,
                    configured=True,
                    attempted=True,
                    error=str(error),
                    query=request.search_queries[0] if request.search_queries else None,
                )
            )
            errors.append(str(error))
            continue
        logger.info(
            "Job discovery provider completed: %s",
            json.dumps(
                {
                    "providerName": provider.provider_name,
                    "providerType": provider.provider_type,
                    "resultCount": len(outcome.results),
                    "diagnosticCount": len(outcome.diagnostics),
                    "errorCount": len(outcome.errors),
                },
                sort_keys=True,
            ),
        )
        results.extend(outcome.results)
        diagnostics.extend(outcome.diagnostics)
        errors.extend(outcome.errors)
    return ProviderSearchOutcome(results=results, diagnostics=diagnostics, errors=errors)


def should_tolerate_partial_company_board_errors(
    outcome: ProviderSearchOutcome,
    search_plan: JobSearchPlan,
) -> bool:
    if search_plan.search_mode not in {"company_specific", "followed_companies"}:
        return False
    if not outcome.results:
        return False
    return any(
        diagnostic.provider_type == "ats_board" and diagnostic.attempted and diagnostic.result_count > 0
        for diagnostic in outcome.diagnostics
    )


def route_job_discovery_providers(
    providers: list[JobDiscoveryProvider],
    request: JobSearchRequest,
) -> tuple[list[JobDiscoveryProvider], list[ProviderDiagnostic]]:
    search_mode = request.search_plan.search_mode if request.search_plan is not None else "broad"
    if search_mode == "broad":
        return providers, []

    provider_by_name = {provider.provider_name: provider for provider in providers}
    broad_providers = [provider for provider in providers if provider.provider_type == "broad_search"]
    routed: list[JobDiscoveryProvider] = []
    diagnostics: list[ProviderDiagnostic] = []

    company_names = request.company_names or []
    target_companies = saved_companies_for_search(request.current_saved_companies, company_names, include_all=search_mode == "followed_companies")
    greenhouse_companies = [company for company in target_companies if saved_company_has_greenhouse_metadata(company)]
    ashby_companies = [company for company in target_companies if saved_company_has_ashby_metadata(company)]
    fallback_companies = [
        company
        for company in target_companies
        if not saved_company_has_greenhouse_metadata(company) and not saved_company_has_ashby_metadata(company)
    ]

    if greenhouse_companies and "greenhouse" in provider_by_name:
        routed.append(provider_by_name["greenhouse"])
        diagnostics.append(
            ProviderDiagnostic(
                provider_name="greenhouse",
                provider_type="ats_board",
                configured=True,
                attempted=False,
                company_name=", ".join(str(company.get("name")) for company in greenhouse_companies if company.get("name"))[:240] or None,
                search_mode=search_mode,
                reason="saved_company_board_token",
            )
        )
    elif greenhouse_companies:
        from .providers.greenhouse import GreenhouseJobDiscoveryProvider

        routed.append(GreenhouseJobDiscoveryProvider())
        diagnostics.append(
            ProviderDiagnostic(
                provider_name="greenhouse",
                provider_type="ats_board",
                configured=True,
                attempted=False,
                company_name=", ".join(str(company.get("name")) for company in greenhouse_companies if company.get("name"))[:240] or None,
                search_mode=search_mode,
                reason="saved_company_board_token_dynamic_provider",
            )
        )
    if ashby_companies and "ashby" in provider_by_name:
        routed.append(provider_by_name["ashby"])
        diagnostics.append(
            ProviderDiagnostic(
                provider_name="ashby",
                provider_type="ats_board",
                configured=True,
                attempted=False,
                company_name=", ".join(str(company.get("name")) for company in ashby_companies if company.get("name"))[:240] or None,
                search_mode=search_mode,
                reason="saved_company_ashby_metadata",
            )
        )

    if fallback_companies or not routed:
        routed.extend(broad_providers)
        if broad_providers:
            diagnostics.append(
                ProviderDiagnostic(
                    provider_name=",".join(provider.provider_name for provider in broad_providers),
                    provider_type="broad_search",
                    configured=True,
                    attempted=False,
                    company_name=", ".join(str(company.get("name")) for company in fallback_companies if company.get("name"))[:240] or None,
                    search_mode=search_mode,
                    reason="broad_fallback_for_companies_without_known_ats_source" if fallback_companies else "no_company_board_provider_available",
                )
            )

    if not routed:
        routed = providers
    seen: set[str] = set()
    deduped: list[JobDiscoveryProvider] = []
    for provider in routed:
        if provider.provider_name in seen:
            continue
        seen.add(provider.provider_name)
        deduped.append(provider)
    return deduped, diagnostics


def provider_is_configured_for_request(provider: JobDiscoveryProvider, request: JobSearchRequest, settings: Settings) -> bool:
    if provider.provider_name != "greenhouse":
        return False
    from .providers.greenhouse import resolve_greenhouse_board_tokens

    return bool(resolve_greenhouse_board_tokens(settings, request=request))


def saved_companies_for_search(
    companies: list[dict[str, Any]],
    company_names: list[str],
    *,
    include_all: bool,
) -> list[dict[str, Any]]:
    if include_all:
        return companies
    requested = {name.casefold() for name in company_names if name}
    if not requested:
        return []
    return [company for company in companies if saved_company_matches_requested_names(company, requested)]


def saved_company_matches_requested_names(company: dict[str, Any], requested: set[str]) -> bool:
    from .providers.greenhouse import greenhouse_board_token_from_company

    name = str(company.get("name") or "").casefold()
    token = (greenhouse_board_token_from_company(company) or "").casefold()
    aliases = {name, token}
    aliases.update(part for part in name.split() if len(part) >= 3)
    return any(value in aliases or (value and value in name) for value in requested)


def saved_company_has_greenhouse_metadata(company: dict[str, Any]) -> bool:
    from .providers.greenhouse import greenhouse_board_token_from_company

    return bool(greenhouse_board_token_from_company(company))


def saved_company_has_ashby_metadata(company: dict[str, Any]) -> bool:
    return bool(company.get("ashby_board_url") or company.get("ashbyBoardUrl"))


def build_candidate_pool(
    source_results: list[LiveJobSourceResult],
    *,
    current_saved_jobs: list[dict[str, Any]],
    user_constraints: list[str],
    save_limit: int,
    candidate_pool_limit: int,
    company_cap: int,
    relevance_terms: list[str],
) -> CandidatePoolBuildResult:
    normalized_results = [result for result in source_results if normalize_job_url(result.job_url)]
    deduped_results = dedupe_provider_results(normalized_results)
    saved_urls = {url.casefold() for url in current_saved_job_urls(current_saved_jobs)}
    skipped: list[SkippedJobResult] = []
    hard_filtered: list[LiveJobSourceResult] = []
    for result in deduped_results:
        normalized_url = normalize_job_url(result.job_url)
        if normalized_url and normalized_url.casefold() in saved_urls:
            skipped.append(skip_from_source_result(result, "duplicate_for_user", "Job is already saved for this profile."))
            continue
        excluded_term = result_matches_exclusion(result, user_constraints)
        if excluded_term:
            skipped.append(
                skip_from_source_result(
                    result,
                    "excluded_by_user_constraints",
                    f"Result matched excluded user constraint: {excluded_term}.",
                )
            )
            continue
        hard_filtered.append(result)

    scored = sorted(
        hard_filtered,
        key=lambda result: rough_candidate_score(result, user_constraints, relevance_terms),
        reverse=True,
    )
    diverse_results: list[LiveJobSourceResult] = []
    company_counts: dict[str, int] = {}
    provider_counts: dict[str, int] = {}
    trimmed_by_company = 0
    trimmed_by_provider = 0
    provider_cap = max(candidate_pool_limit // 2, save_limit * 2, 10)
    for result in scored:
        company_key = normalize_company_name(result.company_name) or result.company_name.casefold()
        provider_key = result.source_provider.casefold()
        if company_cap > 0 and company_counts.get(company_key, 0) >= company_cap:
            trimmed_by_company += 1
            continue
        if provider_cap > 0 and provider_counts.get(provider_key, 0) >= provider_cap:
            trimmed_by_provider += 1
            continue
        diverse_results.append(result)
        company_counts[company_key] = company_counts.get(company_key, 0) + 1
        provider_counts[provider_key] = provider_counts.get(provider_key, 0) + 1
        if len(diverse_results) >= candidate_pool_limit:
            break

    entries = [
        CandidatePoolEntry(
            candidate_id=f"{JOB_DISCOVERY_SELECTION_CANDIDATE_PREFIX}{index:03d}",
            result=result,
            rough_score=rough_candidate_score(result, user_constraints, relevance_terms),
            flags=tuple(candidate_flags(result, user_constraints)),
        )
        for index, result in enumerate(diverse_results, start=1)
    ]
    return CandidatePoolBuildResult(
        entries=entries,
        skipped=skipped,
        count_after_provider_normalization=len(normalized_results),
        count_after_dedupe=len(deduped_results),
        count_after_hard_exclusion_filter=len(hard_filtered),
        count_after_diversity_cap=len(entries),
        trimmed_by_company_cap_count=trimmed_by_company,
        trimmed_by_provider_cap_count=trimmed_by_provider,
    )


def rough_candidate_score(result: LiveJobSourceResult, user_constraints: list[str], relevance_terms: list[str]) -> int:
    text = " ".join(
        part
        for part in [
            result.title,
            result.company_name,
            result.description_excerpt or "",
            result.location or "",
        ]
        if part
    ).casefold()
    title_text = result.title.casefold()
    description_text = (result.description_excerpt or "").casefold()
    score = 0
    for term in relevance_terms[:20]:
        normalized_term = term.casefold()
        if not normalized_term:
            continue
        if normalized_term in title_text:
            score += 8
        elif normalized_term in description_text:
            score += 3
        term_tokens = meaningful_relevance_tokens(normalized_term)
        if term_tokens:
            title_matches = sum(1 for token in term_tokens if token in title_text)
            text_matches = sum(1 for token in term_tokens if token in text)
            score += min(title_matches * 3, 9)
            score += min(text_matches, 6)
    source_query_tokens = meaningful_relevance_tokens(result.source_query or "")
    if source_query_tokens:
        score += min(sum(1 for token in source_query_tokens if token in text), 6)
    if result.remote_work_mode == "remote":
        score += 2
    if result.posting_date:
        score += 1
    if result_matches_exclusion(result, user_constraints):
        score -= 100
    return score


def candidate_flags(result: LiveJobSourceResult, user_constraints: list[str]) -> list[str]:
    flags: list[str] = []
    if result_matches_exclusion(result, user_constraints):
        flags.append("matches_user_exclusion")
    if not result.posting_date:
        flags.append("posting_date_unknown")
    if result.provider_type == "ats_board":
        flags.append("company_board")
    return flags




def dedupe_provider_results(results: list[LiveJobSourceResult]) -> list[LiveJobSourceResult]:
    deduped: list[LiveJobSourceResult] = []
    seen_urls: set[str] = set()
    seen_provider_ids: set[tuple[str, str]] = set()
    for result in results:
        normalized_url = normalize_job_url(result.job_url)
        provider_key = (result.source_provider, result.source_result_id or "")
        if normalized_url and normalized_url in seen_urls:
            continue
        if provider_key[1] and provider_key in seen_provider_ids:
            continue
        if normalized_url:
            seen_urls.add(normalized_url)
        if provider_key[1]:
            seen_provider_ids.add(provider_key)
        deduped.append(result)
    return deduped


EXPLICIT_EXCLUSION_RE = re.compile(
    r"\b(?:avoid|exclude|excluding|without|dont\s+want|do\s+not\s+want|don't\s+want|no)\b(?P<body>[^.?!\n]+)",
    flags=re.IGNORECASE,
)


def infer_user_constraint_terms(latest_user_message: str, target_context: dict[str, Any], private_profile_context: dict[str, Any]) -> list[str]:
    constraints: list[str] = []
    constraints.extend(extract_explicit_exclusion_terms(latest_user_message))
    constraints.extend(extract_structured_constraint_terms(target_context))
    constraints.extend(extract_structured_constraint_terms(private_profile_context))
    return compact_unique_strings(constraints, limit=30)


def extract_explicit_exclusion_terms(value: object) -> list[str]:
    text = clean_text_value(value)
    if not text:
        return []
    terms: list[str] = []
    for match in EXPLICIT_EXCLUSION_RE.finditer(text):
        terms.extend(normalize_exclusion_terms(match.group("body")))
    return terms


def extract_structured_constraint_terms(value: object) -> list[str]:
    terms: list[str] = []
    for item in iter_structured_constraint_values(value):
        if isinstance(item, str):
            terms.extend(extract_explicit_exclusion_terms(item) or normalize_exclusion_terms(item))
        elif isinstance(item, (list, tuple, set)):
            for nested in item:
                if isinstance(nested, str):
                    terms.extend(extract_explicit_exclusion_terms(nested) or normalize_exclusion_terms(nested))
                else:
                    terms.extend(extract_structured_constraint_terms(nested))
        elif isinstance(item, dict):
            terms.extend(extract_structured_constraint_terms(item))
    return terms


def iter_structured_constraint_values(value: object) -> list[object]:
    if not isinstance(value, dict):
        return []
    values: list[object] = []
    for key, item in value.items():
        key_text = str(key).casefold()
        if any(marker in key_text for marker in ("avoid", "exclude", "constraint", "restriction", "dealbreaker", "red_flag")):
            values.append(item)
            continue
        if isinstance(item, dict):
            values.extend(iter_structured_constraint_values(item))
        elif isinstance(item, list):
            for nested in item:
                values.extend(iter_structured_constraint_values(nested))
    return values


def result_matches_exclusion(result: LiveJobSourceResult, constraints: list[str]) -> str | None:
    haystack = normalize_text_for_constraint_matching(
        " ".join(
            str(value or "")
            for value in [result.title, result.company_name, result.description_excerpt, result.source_provider, result.salary_text]
        )
    )
    for term in constraints:
        normalized_term = normalize_text_for_constraint_matching(term)
        if normalized_term and normalized_term in haystack:
            return term
    return None



def build_provider_job_search_queries(
    request: JobDiscoveryRequest,
    *,
    current_saved_companies: list[dict[str, Any]],
    target_context: dict[str, Any],
    private_profile_context: dict[str, Any],
) -> list[str]:
    role_queries = infer_job_search_role_queries(
        request.latest_user_message,
        target_context=target_context,
        private_profile_context=private_profile_context,
    )
    queries: list[str] = []
    queries.extend(role_queries[:5])

    message = request.latest_user_message.casefold()
    if "remote" in message:
        queries.extend([f"Remote {role}" for role in role_queries[:3]])

    # Broad job APIs expect role-like search terms, while company ATS providers use
    # configured boards rather than site: queries. Saved companies remain in context
    # for provider selection and fit summaries without polluting provider keywords.
    _ = current_saved_companies

    return compact_unique_strings(queries, limit=12)


def build_provider_job_search_queries_from_plan(
    request: JobDiscoveryRequest,
    *,
    search_plan: JobSearchPlan,
    current_saved_companies: list[dict[str, Any]],
    target_context: dict[str, Any],
    private_profile_context: dict[str, Any],
) -> list[str]:
    role_queries = search_plan.role_queries or infer_job_search_role_queries(
        request.latest_user_message,
        target_context=target_context,
        private_profile_context=private_profile_context,
    )
    role_queries = [query for query in role_queries if query and query.casefold() not in {"job", "jobs"}] or ["jobs"]
    queries: list[str] = []

    if search_plan.search_mode in {"company_specific", "followed_companies"} and search_plan.company_names:
        for company_name in search_plan.company_names:
            for role in role_queries[:3]:
                queries.append(compact_provider_query([company_name, role, *search_plan.remote_work_modes[:1]]))
        if search_plan.search_mode == "company_specific":
            return compact_unique_strings(queries, limit=12)

    for role in role_queries[:6]:
        query_parts = [role]
        if "remote" in search_plan.remote_work_modes and "remote" not in role.casefold():
            query_parts.append("remote")
        queries.append(compact_provider_query(query_parts))

    _ = current_saved_companies
    return compact_unique_strings(queries, limit=12)


def compact_provider_query(parts: list[str]) -> str:
    return " ".join(part for part in (" ".join(str(part).split()).strip() for part in parts) if part)


def build_fresh_job_search_queries(
    request: JobDiscoveryRequest,
    *,
    current_saved_companies: list[dict[str, Any]],
    target_context: dict[str, Any],
    private_profile_context: dict[str, Any],
) -> list[str]:
    role_queries = infer_job_search_role_queries(
        request.latest_user_message,
        target_context=target_context,
        private_profile_context=private_profile_context,
    )
    remote_term = " remote" if "remote" in request.latest_user_message.casefold() else ""
    queries: list[str] = []
    for role in role_queries[:4]:
        queries.extend(
            [
                f'"{role}"{remote_term} current job posting apply',
                f'"{role}"{remote_term} careers job opening',
            ]
        )

    for company in current_saved_companies[:8]:
        domain = domain_from_url(
            company.get("job_listings_url")
            or company.get("jobListingsUrl")
            or company.get("careers_url")
            or company.get("careersUrl")
            or company.get("website_url")
            or company.get("websiteUrl")
        )
        if not domain:
            continue
        role = role_queries[0] if role_queries else "jobs"
        queries.append(f'site:{domain} "{role}" jobs careers apply')

    return compact_unique_strings(queries, limit=12)


def build_job_relevance_terms(
    latest_user_message: str,
    *,
    search_queries: list[str],
    target_context: dict[str, Any],
    private_profile_context: dict[str, Any],
    search_plan: JobSearchPlan | None = None,
) -> list[str]:
    terms: list[str] = []
    terms.extend(search_queries)
    if search_plan is not None:
        terms.extend(search_plan.role_queries)
        terms.extend(search_plan.include_terms)
        terms.extend(search_plan.company_names)
        terms.extend(search_plan.locations)
    terms.extend(infer_job_search_role_queries(latest_user_message, target_context=target_context, private_profile_context=private_profile_context))
    terms.extend(coerce_string_list(target_context.get("skills")))
    terms.extend(coerce_string_list(target_context.get("keywords")))
    basics = private_profile_context.get("profile_basics") if isinstance(private_profile_context, dict) else None
    if isinstance(basics, dict):
        terms.extend(coerce_string_list(basics.get("headline")))
    for key in ("skills", "keywords", "interests", "preferences"):
        terms.extend(coerce_string_list(private_profile_context.get(key)))
    return compact_unique_strings(terms, limit=30)


def infer_job_search_role_queries(
    latest_user_message: str,
    *,
    target_context: dict[str, Any],
    private_profile_context: dict[str, Any],
) -> list[str]:
    roles: list[str] = []
    roles.extend(extract_role_queries_from_message(latest_user_message))
    roles.extend(extract_explicit_target_titles(target_context, private_profile_context))
    roles.extend(extract_target_role_families(target_context, private_profile_context))
    roles.extend(extract_profile_headline_role(private_profile_context))
    roles.extend(extract_target_domains_or_industries(target_context, private_profile_context))
    roles.extend(extract_previous_profile_titles(private_profile_context))
    roles.extend(extract_profile_skills(private_profile_context))
    if not roles:
        roles.extend(extract_generic_profile_role_queries(private_profile_context))
    if not roles and discovery_request_allows_broad_results(latest_user_message):
        roles.append("jobs")
    if not roles and latest_user_message.strip():
        phrase = clean_role_query_phrase(latest_user_message)
        if phrase and phrase.casefold() not in {"find jobs", "find me jobs", "please find jobs"}:
            roles.append(title_case_role_query(phrase))
    if not roles:
        roles.append("jobs")
    return compact_unique_strings(roles, limit=6)


def extract_explicit_target_titles(
    target_context: dict[str, Any],
    private_profile_context: dict[str, Any],
) -> list[str]:
    values: list[str] = []
    values.extend(coerce_string_list(target_context.get("target_role_titles")))
    targets = private_profile_context.get("targets") if isinstance(private_profile_context, dict) else None
    if isinstance(targets, dict):
        values.extend(coerce_string_list(targets.get("targetTitles")))
        values.extend(coerce_string_list(targets.get("target_role_titles")))
    for item_key in ("published_internal_items", "published_public_items"):
        items = private_profile_context.get(item_key) if isinstance(private_profile_context, dict) else None
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict) or item.get("collection") != "targetRoleIntent":
                continue
            values.extend(coerce_string_list(item.get("targetTitles")))
            values.extend(coerce_string_list(item.get("target_role_titles")))
    return values


def extract_target_role_families(
    target_context: dict[str, Any],
    private_profile_context: dict[str, Any],
) -> list[str]:
    values: list[str] = []
    values.extend(coerce_search_term_list(target_context.get("target_role_families")))
    values.extend(coerce_search_term_list(target_context.get("role_families")))
    targets = private_profile_context.get("targets") if isinstance(private_profile_context, dict) else None
    if isinstance(targets, dict):
        values.extend(coerce_search_term_list(targets.get("targetRoleFamilies")))
        values.extend(coerce_search_term_list(targets.get("target_role_families")))
        values.extend(coerce_search_term_list(targets.get("roleFamilies")))
    for item in iter_private_profile_items(private_profile_context):
        if not isinstance(item, dict) or item.get("collection") != "targetRoleIntent":
            continue
        values.extend(coerce_search_term_list(item.get("targetRoleFamilies")))
        values.extend(coerce_search_term_list(item.get("target_role_families")))
        values.extend(coerce_search_term_list(item.get("roleFamilies")))
    return values


def extract_target_domains_or_industries(
    target_context: dict[str, Any],
    private_profile_context: dict[str, Any],
) -> list[str]:
    values: list[str] = []
    values.extend(coerce_search_term_list(target_context.get("domains_or_industries")))
    values.extend(coerce_search_term_list(target_context.get("domainsOrIndustries")))
    targets = private_profile_context.get("targets") if isinstance(private_profile_context, dict) else None
    if isinstance(targets, dict):
        values.extend(coerce_search_term_list(targets.get("domainsOrIndustries")))
        values.extend(coerce_search_term_list(targets.get("domains_or_industries")))
    for item in iter_private_profile_items(private_profile_context):
        if not isinstance(item, dict) or item.get("collection") != "targetRoleIntent":
            continue
        values.extend(coerce_search_term_list(item.get("domainsOrIndustries")))
        values.extend(coerce_search_term_list(item.get("domains_or_industries")))
    return values


def extract_role_queries_from_message(latest_user_message: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", latest_user_message).strip()
    patterns = [
        r"\bfind\s+(?:me\s+)?(?:some\s+)?(.+?)\s+(?:jobs|roles|positions)\b",
        r"\bshow\s+(?:me\s+)?(.+?)\s+(?:jobs|roles|positions)\b",
    ]
    roles: list[str] = []
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if not match:
            continue
        phrase = clean_role_query_phrase(match.group(1))
        if phrase:
            roles.append(title_case_role_query(phrase))
    return roles


def extract_previous_profile_titles(private_profile_context: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for item in iter_private_profile_items(private_profile_context):
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or item.get("itemType") or "").casefold()
        collection = str(item.get("collection") or "").casefold()
        if item_type != "experience" and collection != "experienceandprojects":
            continue
        title = clean_role_query_phrase(str(item.get("title") or ""))
        if title and not profile_role_candidate_is_placeholder(title):
            values.append(title)
    return values


def extract_profile_skills(private_profile_context: dict[str, Any]) -> list[str]:
    values: list[str] = []
    values.extend(coerce_search_term_list(private_profile_context.get("skills")))
    for item in iter_private_profile_items(private_profile_context):
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").casefold()
        collection = str(item.get("collection") or "").casefold()
        if item_type != "skill" and collection != "skillclaims":
            continue
        values.extend(coerce_search_term_list(item.get("skill")))
    return values


def iter_private_profile_items(private_profile_context: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(private_profile_context, dict):
        return []
    items: list[dict[str, Any]] = []
    for key in ("published_internal_items", "published_public_items", "draft_items"):
        raw_items = private_profile_context.get(key)
        if not isinstance(raw_items, list):
            continue
        items.extend(item for item in raw_items if isinstance(item, dict))
    return items


def extract_profile_headline_role(private_profile_context: dict[str, Any]) -> list[str]:
    basics = private_profile_context.get("profile_basics") if isinstance(private_profile_context, dict) else None
    headline = clean_text_value(basics.get("headline")) if isinstance(basics, dict) else None
    if not headline:
        return []
    candidate = re.split(r"\s+[|•]\s+|\s+-\s+|\s+with\s+", headline, maxsplit=1, flags=re.IGNORECASE)[0]
    candidate = clean_role_query_phrase(candidate)
    if not candidate or profile_role_candidate_is_placeholder(candidate):
        return []
    return [candidate]


def extract_generic_profile_role_queries(private_profile_context: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("desired_roles", "target_roles", "roles"):
        values.extend(coerce_string_list(private_profile_context.get(key)))
    return [value for value in values if not profile_role_candidate_is_placeholder(value)]


def profile_role_candidate_is_placeholder(value: str) -> bool:
    normalized = value.casefold()
    return normalized in {"candidate", "profile", "candidate profile setup in progress"} or "setup in progress" in normalized


def meaningful_relevance_tokens(value: str) -> list[str]:
    stop_words = {
        "and",
        "apply",
        "careers",
        "current",
        "find",
        "for",
        "job",
        "jobs",
        "me",
        "more",
        "new",
        "open",
        "opening",
        "opportunities",
        "opportunity",
        "please",
        "position",
        "positions",
        "remote",
        "role",
        "roles",
        "some",
        "the",
        "to",
    }
    tokens: list[str] = []
    for raw in re.findall(r"[a-z0-9]+", value.casefold()):
        if len(raw) < 3 or raw in stop_words:
            continue
        tokens.append(raw)
    return compact_unique_strings(tokens, limit=8)


def clean_role_query_phrase(value: str) -> str | None:
    cleaned = re.sub(r"\b(remote|hybrid|onsite|on-site|some|more|new|open|current|to apply to|for me)\b", " ", value, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(that fit my profile|like this|i should consider)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[\"'`]+", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.;:-")
    if not cleaned or cleaned.casefold() in {"jobs", "roles", "positions"}:
        return None
    return cleaned


def title_case_role_query(value: str) -> str:
    small_words = {"ai", "ml", "llm", "rag", "api", "ux", "ui"}
    words = []
    for word in value.split():
        lookup = re.sub(r"[^A-Za-z0-9]", "", word).casefold()
        words.append(word.upper() if lookup in small_words else word[:1].upper() + word[1:])
    return " ".join(words)


def coerce_string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.replace("\n", ";").split(";") if part.strip()]
    if isinstance(value, (list, tuple)):
        return [str(part).strip() for part in value if str(part).strip()]
    return []


def coerce_search_term_list(value: object) -> list[str]:
    terms: list[str] = []
    for item in coerce_string_list(value):
        terms.extend(part.strip() for part in re.split(r"[;\n,|]+", item) if part.strip())
    return compact_unique_strings(terms, limit=12)


def current_saved_job_urls(current_saved_jobs: list[dict[str, Any]]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for job in current_saved_jobs:
        for key in ("job_url", "normalized_url"):
            value = job.get(key)
            if not isinstance(value, str):
                continue
            cleaned = value.strip()
            if not cleaned:
                continue
            normalized = normalize_job_url(cleaned) or cleaned
            lookup = normalized.casefold()
            if lookup in seen:
                continue
            seen.add(lookup)
            urls.append(normalized)
    return urls


def load_recent_job_search_history(session: Session, candidate_profile_id: str, *, limit: int) -> list[dict[str, Any]]:
    capped_limit = max(1, min(limit, 50))
    runs = list(
        session.scalars(
            select(JobSearchRun)
            .where(JobSearchRun.candidate_profile_id == candidate_profile_id)
            .order_by(JobSearchRun.created_at.desc())
            .limit(capped_limit)
        )
    )
    if not runs:
        return []
    run_ids = [run.id for run in runs]
    query_runs = list(
        session.scalars(
            select(JobSearchQueryRun)
            .where(JobSearchQueryRun.job_search_run_id.in_(run_ids))
            .order_by(JobSearchQueryRun.created_at.desc())
            .limit(capped_limit * 4)
        )
    )
    queries_by_run: dict[str, list[JobSearchQueryRun]] = {}
    for query_run in query_runs:
        queries_by_run.setdefault(query_run.job_search_run_id, []).append(query_run)
    return [serialize_recent_job_search_run(run, queries_by_run.get(run.id, [])[:8]) for run in runs]


def serialize_recent_job_search_run(run: JobSearchRun, query_runs: list[JobSearchQueryRun]) -> dict[str, Any]:
    return {
        "id": run.id,
        "command_text": safe_log_preview(run.command_text, limit=240),
        "search_mode": run.search_mode,
        "status": run.status,
        "provider_names": run.provider_names or [],
        "searched_role_queries": (run.search_plan_json or {}).get("roleQueries") or (run.search_plan_json or {}).get("role_queries") or [],
        "searched_companies": (run.search_plan_json or {}).get("companyNames") or (run.search_plan_json or {}).get("company_names") or [],
        "total_provider_results": run.total_provider_results,
        "total_matches_reported": run.total_matches_reported,
        "candidate_pool_count": run.candidate_pool_count,
        "candidate_count_after_dedupe": run.candidate_count_after_dedupe,
        "replans_attempted": run.replans_attempted,
        "model_selected_count": run.model_selected_count,
        "saved_count": run.saved_count,
        "updated_existing_count": run.updated_existing_count,
        "duplicate_count": run.duplicate_count,
        "skipped_count": run.skipped_count,
        "provider_error_count": run.provider_error_count,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "queries": [
            {
                "provider_name": query.provider_name,
                "query": safe_log_preview(query.query or "", limit=160) or None,
                "company_name": query.company_name,
                "location": query.location,
                "page": query.page,
                "total_matches": query.total_matches,
                "raw_result_count": query.raw_result_count,
                "normalized_result_count": query.normalized_result_count,
                "candidate_count_after_filters": query.candidate_count_after_filters,
                "error": safe_log_preview(query.error or "", limit=160) or None,
            }
            for query in query_runs
        ],
    }


def serialize_job_search_run_status(run: JobSearchRun, query_runs: list[JobSearchQueryRun]) -> dict[str, Any]:
    provider_error_count = run.provider_error_count or sum(1 for query in query_runs if query.error)
    diagnostics = run.run_diagnostics_json if isinstance(run.run_diagnostics_json, dict) else {}
    planner = diagnostics.get("planner") if isinstance(diagnostics.get("planner"), dict) else {}
    selection = diagnostics.get("selection") if isinstance(diagnostics.get("selection"), dict) else {}
    replanning = diagnostics.get("replanning") if isinstance(diagnostics.get("replanning"), dict) else {}
    return {
        "id": run.id,
        "status": run.status,
        "searchMode": run.search_mode,
        "createdAt": run.created_at.isoformat() if run.created_at else None,
        "startedAt": run.started_at.isoformat() if run.started_at else None,
        "completedAt": run.completed_at.isoformat() if run.completed_at else None,
        "providerResultCount": run.total_provider_results,
        "candidatePoolCount": run.candidate_pool_count,
        "candidateCountAfterDedupe": run.candidate_count_after_dedupe,
        "modelSelectedCount": run.model_selected_count,
        "savedCount": run.saved_count,
        "updatedExistingCount": run.updated_existing_count,
        "duplicateCount": run.duplicate_count,
        "skippedCount": run.skipped_count,
        "providerErrorCount": provider_error_count,
        "error": safe_log_preview(run.error or "", limit=500) or None,
        "message": build_job_search_run_status_message(run, provider_error_count=provider_error_count),
        "userVisibleSummary": clean_user_facing_explanation(
            diagnostics.get("userVisibleSummary") or diagnostics.get("userSummary"),
            limit=900,
        ),
        "userSummary": clean_user_facing_explanation(diagnostics.get("userSummary"), limit=900),
        "plannerRationale": clean_user_facing_explanation(planner.get("rationale"), limit=900),
        "plannerFallbackUsed": bool(planner.get("fallbackUsed")) if "fallbackUsed" in planner else None,
        "recentSearchesUsed": int(planner.get("recentSearchesUsedCount") or 0),
        "selectionAssistantMessage": clean_user_facing_explanation(selection.get("assistantMessage"), limit=900),
        "selectionSkippedCandidateNotes": selection.get("skippedCandidateNotes") if isinstance(selection.get("skippedCandidateNotes"), list) else [],
        "selectionClarifyingQuestions": selection.get("clarifyingQuestions") if isinstance(selection.get("clarifyingQuestions"), list) else [],
        "replansAttempted": int(replanning.get("replansAttempted") or run.replans_attempted or 0),
        "replanLimit": replanning.get("replanLimit"),
        "replanningStatus": clean_user_facing_explanation(replanning.get("replanningStatus"), limit=120),
        "replanningDecision": clean_user_facing_explanation(replanning.get("replanningDecision"), limit=160),
        "replanReason": clean_user_facing_explanation(replanning.get("replanReason"), limit=160),
        "replanReasons": replanning.get("replanReasons") if isinstance(replanning.get("replanReasons"), list) else [],
        "replanQueries": replanning.get("replanQueries") if isinstance(replanning.get("replanQueries"), list) else [],
    }


def build_job_search_run_status_message(run: JobSearchRun, *, provider_error_count: int) -> str:
    if run.status in {"queued", "started"}:
        return "Job discovery is queued and will start shortly."
    if run.status == "running":
        return "Job discovery is running. Saved jobs will update when the search completes."
    if run.status == "completed":
        diagnostics = run.run_diagnostics_json if isinstance(run.run_diagnostics_json, dict) else {}
        user_summary = clean_user_facing_explanation(
            diagnostics.get("userVisibleSummary") or diagnostics.get("userSummary"),
            limit=900,
        )
        if user_summary:
            return user_summary
        return (
            "Job discovery completed: "
            f"{run.saved_count} new job(s) saved, "
            f"{run.updated_existing_count} refreshed, "
            f"{run.duplicate_count} duplicate(s), "
            f"{run.skipped_count} skipped."
        )
    if run.status == "failed":
        return "Job discovery failed. No browser replay was attempted."
    if provider_error_count:
        return f"Job discovery finished with {provider_error_count} provider error(s)."
    return f"Job discovery status: {run.status}."


def get_existing_job_search_run(session: Session, run_id: str | None, candidate_profile_id: str) -> JobSearchRun | None:
    if not run_id:
        return None
    return session.scalar(
        select(JobSearchRun).where(
            JobSearchRun.id == run_id,
            JobSearchRun.candidate_profile_id == candidate_profile_id,
        )
    )


def create_job_search_run(
    session: Session,
    *,
    candidate_profile: CandidateProfile,
    command_text: str,
    search_plan: JobSearchPlan,
    provider_names: tuple[str, ...],
) -> JobSearchRun:
    run = JobSearchRun(
        candidate_profile_id=candidate_profile.id,
        command_text=command_text,
        search_plan_json=search_plan.model_dump(by_alias=True),
        provider_names=list(provider_names),
        search_mode=search_plan.search_mode,
        status="started",
        total_provider_results=0,
        candidate_pool_count=0,
        candidate_count_after_dedupe=0,
        replans_attempted=0,
        model_selected_count=0,
        saved_count=0,
        updated_existing_count=0,
        duplicate_count=0,
        skipped_count=0,
        provider_error_count=0,
        started_at=datetime.now(timezone.utc),
    )
    session.add(run)
    session.flush()
    return run


def persist_job_search_query_runs(
    session: Session,
    run: JobSearchRun,
    provider_diagnostics: list[ProviderDiagnostic],
    *,
    candidate_pool: CandidatePoolBuildResult | None = None,
) -> None:
    for diagnostic in provider_diagnostics:
        session.add(
            JobSearchQueryRun(
                job_search_run_id=run.id,
                provider_name=diagnostic.provider_name,
                query=diagnostic.query,
                company_name=diagnostic.company_name,
                location=diagnostic.location,
                page=diagnostic.page,
                total_matches=diagnostic.total_matches,
                raw_result_count=diagnostic.raw_result_count or diagnostic.result_count or 0,
                normalized_result_count=diagnostic.normalized_result_count
                if diagnostic.normalized_result_count is not None
                else diagnostic.result_count,
                deduped_result_count=diagnostic.deduped_result_count
                if diagnostic.deduped_result_count is not None
                else diagnostic.result_count,
                candidate_count_after_filters=diagnostic.candidate_count_after_filters
                if diagnostic.candidate_count_after_filters is not None
                else (candidate_pool.count_after_hard_exclusion_filter if candidate_pool is not None else 0),
                error=diagnostic.error,
            )
        )


def complete_job_search_run(
    run: JobSearchRun,
    *,
    status: str,
    provider_diagnostics: list[ProviderDiagnostic],
    total_provider_results: int = 0,
    candidate_pool_count: int = 0,
    candidate_count_after_dedupe: int = 0,
    replans_attempted: int = 0,
    model_selected_count: int = 0,
    saved_count: int = 0,
    updated_existing_count: int = 0,
    duplicate_count: int = 0,
    skipped_count: int = 0,
    provider_error_count: int | None = None,
    run_diagnostics: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    run.status = status
    run.total_provider_results = total_provider_results
    run.total_matches_reported = total_matches_reported(provider_diagnostics)
    run.candidate_pool_count = candidate_pool_count
    run.candidate_count_after_dedupe = candidate_count_after_dedupe
    run.replans_attempted = replans_attempted
    run.model_selected_count = model_selected_count
    run.saved_count = saved_count
    run.updated_existing_count = updated_existing_count
    run.duplicate_count = duplicate_count
    run.skipped_count = skipped_count
    run.provider_error_count = (
        provider_error_count
        if provider_error_count is not None
        else sum(1 for diagnostic in provider_diagnostics if diagnostic.error)
    )
    run.error = error
    if run_diagnostics is not None:
        run.run_diagnostics_json = run_diagnostics
    run.started_at = run.started_at or datetime.now(timezone.utc)
    run.completed_at = datetime.now(timezone.utc)


def total_matches_reported(provider_diagnostics: list[ProviderDiagnostic]) -> int | None:
    values = [diagnostic.total_matches for diagnostic in provider_diagnostics if diagnostic.total_matches is not None]
    return sum(values) if values else None


def provider_raw_result_count(provider_diagnostics: list[ProviderDiagnostic], fallback: int) -> int:
    values = [diagnostic.raw_result_count for diagnostic in provider_diagnostics if diagnostic.raw_result_count is not None]
    return sum(values) if values else fallback


def total_pages_attempted(provider_diagnostics: list[ProviderDiagnostic]) -> int:
    pages = [diagnostic.page for diagnostic in provider_diagnostics if diagnostic.page is not None]
    if pages:
        return len(pages)
    return sum(diagnostic.pages_attempted or 0 for diagnostic in provider_diagnostics)


def summarize_search_plan(search_plan: JobSearchPlan) -> dict[str, Any]:
    return {
        "searchMode": search_plan.search_mode,
        "roleQueries": search_plan.role_queries,
        "companyNames": search_plan.company_names,
        "locations": search_plan.locations,
        "remoteWorkModes": search_plan.remote_work_modes,
        "salaryMin": search_plan.salary_min,
        "excludeTerms": search_plan.exclude_terms,
        "maxProviderPages": search_plan.provider_strategy.max_provider_pages,
    }


def serialize_current_saved_jobs(session: Session, candidate_profile_id: str) -> list[dict[str, Any]]:
    links = list(
        session.scalars(
            select(CandidateSavedJob)
            .where(CandidateSavedJob.candidate_profile_id == candidate_profile_id)
            .order_by(CandidateSavedJob.added_at.desc())
            .limit(50)
        )
    )
    return [
        {
            "saved_job_id": link.id,
            "job_id": link.job.id,
            "title": link.job.title,
            "company_name": link.job.company_name,
            "job_url": link.job.job_url,
            "normalized_url": link.job.normalized_url,
            "status": link.status,
            "added_at": link.added_at.isoformat() if link.added_at else None,
        }
        for link in links
        if link.job is not None
    ]


def save_live_job_source_results(
    session: Session,
    *,
    candidate_profile: CandidateProfile,
    discovery_query: str,
    source_results: list[LiveJobSourceResult],
    search_queries_used: list[str],
    provider: str,
    verify_urls: bool,
    user_constraints: list[str] | None = None,
) -> JobDiscoverySaveResult:
    existing_jobs = {
        job.normalized_url: job
        for job in session.scalars(select(JobPosting))
        if job.normalized_url
    }
    existing_links = {
        link.job_id: link
        for link in session.scalars(
            select(CandidateSavedJob).where(CandidateSavedJob.candidate_profile_id == candidate_profile.id)
        )
    }
    saved_links: list[CandidateSavedJob] = []
    updated_existing_links: list[CandidateSavedJob] = []
    created_jobs: list[JobPosting] = []
    updated_jobs: list[JobPosting] = []
    added_companies: list[CandidateCompany] = []
    skipped: list[SkippedJobResult] = []
    now = datetime.now(timezone.utc)
    seen_in_output: set[str] = set()

    for result in source_results:
        excluded_term = result_matches_exclusion(result, user_constraints or [])
        if excluded_term:
            skipped.append(
                skip_from_source_result(
                    result,
                    "excluded_by_user_constraints",
                    f"Result matched excluded user constraint: {excluded_term}.",
                )
            )
            continue
        normalized_url = normalize_job_url(result.job_url)
        if not normalized_url:
            skipped.append(skip_from_source_result(result, "missing_required_url", "Missing reliable job URL."))
            continue
        if normalized_url in seen_in_output:
            skipped.append(skip_from_source_result(result, "duplicate_global_job", "Duplicate result in provider response."))
            continue
        seen_in_output.add(normalized_url)

        verification = source_result_verification(result, verify_url=verify_urls)
        if verification.expired_or_closed:
            skipped.append(skip_from_source_result(result, "expired_or_closed", verification.summary))
            continue
        if verification.status == "failed":
            skipped.append(skip_from_source_result(result, "failed_url_verification", verification.summary))
            continue
        if result.provenance not in {"provider_result", "fetched_page", "user_url", "mock"}:
            skipped.append(skip_from_source_result(result, "no_live_source_provenance", "Job result did not include live-source provenance."))
            continue

        existing_job = existing_jobs.get(normalized_url)
        if existing_job is not None:
            update_job_posting_from_source_result(existing_job, result, verification=verification, provider=provider, last_seen_at=now)
            updated_jobs.append(existing_job)
        else:
            existing_job = JobPosting(
                title=result.title.strip(),
                company_name=result.company_name.strip(),
                job_url=result.job_url,
                canonical_url=verification.final_url or result.job_url,
                apply_url=result.apply_url or result.job_url,
                normalized_url=normalized_url,
                source=result.source_provider,
                source_provider=result.source_provider,
                provider_type=result.provider_type,
                source_result_id=result.source_result_id,
                source_query=result.source_query,
                source_url=result.source_url or result.job_url,
                source_updated_at=result.source_updated_at,
                provider_raw_metadata=result.raw_metadata or {},
                company_website_url=result.company_website_url,
                company_careers_url=result.company_careers_url,
                ats_provider=result.ats_provider,
                ats_board_token=result.ats_board_token,
                provenance=result.provenance,
                location=result.location,
                remote_work_mode=result.remote_work_mode,
                employment_type=result.employment_type,
                salary_min=result.salary_min,
                salary_max=result.salary_max,
                salary_currency=result.salary_currency,
                salary_text=result.salary_text,
                full_description=result.full_description,
                description_excerpt=verification.description_excerpt or result.description_excerpt,
                discovered_by=provider,
                url_verification_status=verification.status,
                url_verification_checked_at=verification.checked_at,
                url_verification_summary=verification.summary,
                posting_date=result.posting_date or verification.posting_date,
                first_seen_at=now,
                last_seen_at=now,
            )
            session.add(existing_job)
            session.flush()
            created_jobs.append(existing_job)
            existing_jobs[normalized_url] = existing_job

        job_record = source_result_to_job_record(result, verification)
        company_link_result = ensure_candidate_company_for_job(
            session,
            candidate_profile_id=candidate_profile.id,
            job=job_record,
            provider=provider,
            discovery_query=discovery_query,
            ats_provider=result.ats_provider,
            ats_board_token=result.ats_board_token,
        )
        existing_job.company_id = company_link_result.company.id
        if company_link_result.created_link:
            added_companies.append(company_link_result.link)

        if existing_job.id in existing_links:
            link = existing_links[existing_job.id]
            link.fit_summary = result.fit_summary or link.fit_summary
            link.source_command = discovery_query
            link.discovery_metadata = {
                "discovery_query": discovery_query,
                "search_queries_used": search_queries_used,
                "provider": provider,
                "provenance": result.provenance,
                "source_result_id": result.source_result_id,
                "provider_type": result.provider_type,
                "url_verification_status": verification.status,
            }
            updated_existing_links.append(link)
            skipped.append(skip_from_source_result(result, "duplicate_for_user", "Job is already saved for this profile."))
            continue

        link = CandidateSavedJob(
            candidate_profile_id=candidate_profile.id,
            job_id=existing_job.id,
            status="new",
            fit_summary=result.fit_summary,
            user_notes=None,
            source_command=discovery_query,
            discovery_metadata={
                "discovery_query": discovery_query,
                "search_queries_used": search_queries_used,
                "provider": provider,
                "provenance": result.provenance,
                "source_result_id": result.source_result_id,
                "provider_type": result.provider_type,
                "url_verification_status": verification.status,
            },
            added_at=now,
        )
        session.add(link)
        session.flush()
        saved_links.append(link)
        existing_links[existing_job.id] = link

    return JobDiscoverySaveResult(
        saved_links=saved_links,
        updated_existing_links=updated_existing_links,
        created_jobs=created_jobs,
        updated_jobs=updated_jobs,
        added_companies=added_companies,
        skipped=skipped,
    )



def skip_from_source_result(result: LiveJobSourceResult, reason_code: SkipReasonCode, reason: str) -> SkippedJobResult:
    return SkippedJobResult(title=result.title, companyName=result.company_name, jobUrl=result.job_url, reasonCode=reason_code, reason=reason)


def source_result_to_job_record(result: LiveJobSourceResult, verification: JobUrlVerificationResult) -> JobDiscoveryRecord:
    return JobDiscoveryRecord(
        title=result.title,
        companyName=result.company_name,
        jobUrl=result.job_url,
        companyWebsiteUrl=result.company_website_url,
        companyCareersUrl=result.company_careers_url,
        companyJobListingsUrl=result.company_job_listings_url,
        sourceUrls=[url for url in [result.company_job_listings_url, result.source_url, result.job_url, *result.source_urls] if url],
        source=result.source_provider,
        location=result.location,
        remoteWorkMode=result.remote_work_mode or "unknown",
        employmentType=result.employment_type,
        salaryMin=result.salary_min,
        salaryMax=result.salary_max,
        salaryCurrency=result.salary_currency,
        salaryText=result.salary_text,
        descriptionExcerpt=verification.description_excerpt or result.description_excerpt,
        fitSummary=result.fit_summary,
        postingDate=result.posting_date or verification.posting_date,
    )


def update_job_posting_from_source_result(
    job_posting: JobPosting,
    result: LiveJobSourceResult,
    *,
    verification: JobUrlVerificationResult,
    provider: str,
    last_seen_at: datetime,
) -> None:
    job_posting.title = result.title.strip()
    job_posting.company_name = result.company_name.strip()
    job_posting.job_url = result.job_url
    job_posting.canonical_url = verification.final_url or job_posting.canonical_url or result.job_url
    job_posting.apply_url = job_posting.apply_url or result.job_url
    job_posting.source = result.source_provider or job_posting.source or provider
    job_posting.source_provider = result.source_provider
    job_posting.provider_type = result.provider_type
    job_posting.source_result_id = result.source_result_id or job_posting.source_result_id
    job_posting.source_query = result.source_query or job_posting.source_query
    job_posting.source_url = result.source_url or job_posting.source_url or result.job_url
    job_posting.source_updated_at = result.source_updated_at or job_posting.source_updated_at
    job_posting.provider_raw_metadata = result.raw_metadata or job_posting.provider_raw_metadata or {}
    job_posting.company_website_url = result.company_website_url or job_posting.company_website_url
    job_posting.company_careers_url = result.company_careers_url or job_posting.company_careers_url
    job_posting.ats_provider = result.ats_provider or job_posting.ats_provider
    job_posting.ats_board_token = result.ats_board_token or job_posting.ats_board_token
    job_posting.provenance = result.provenance
    job_posting.location = result.location or job_posting.location
    job_posting.remote_work_mode = result.remote_work_mode or job_posting.remote_work_mode
    job_posting.employment_type = result.employment_type or job_posting.employment_type
    job_posting.salary_min = result.salary_min if result.salary_min is not None else job_posting.salary_min
    job_posting.salary_max = result.salary_max if result.salary_max is not None else job_posting.salary_max
    job_posting.salary_currency = result.salary_currency or job_posting.salary_currency
    job_posting.salary_text = result.salary_text or job_posting.salary_text
    job_posting.full_description = result.full_description or job_posting.full_description
    job_posting.description_excerpt = verification.description_excerpt or result.description_excerpt or job_posting.description_excerpt
    job_posting.discovered_by = provider
    job_posting.url_verification_status = verification.status
    job_posting.url_verification_checked_at = verification.checked_at
    job_posting.url_verification_summary = verification.summary
    job_posting.posting_date = result.posting_date or verification.posting_date or job_posting.posting_date
    job_posting.last_seen_at = last_seen_at


def count_verified_source_results(source_results: list[LiveJobSourceResult]) -> int:
    return sum(1 for result in source_results if result.url_verification_status in {"verified", "mock_verified", "provider_unverified"})


def skipped_reason_code_counts(skipped: list[SkippedJobResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in skipped:
        counts[item.reason_code] = counts.get(item.reason_code, 0) + 1
    return counts


def build_live_job_discovery_assistant_message(save_result: JobDiscoverySaveResult, source_results: list[LiveJobSourceResult]) -> str:
    saved_count = len(save_result.saved_links)
    updated_count = len(save_result.updated_existing_links)
    skipped_count = len(save_result.skipped)
    if saved_count:
        message = f"Saved {saved_count} verified job(s) from live source results."
        if updated_count:
            message += f" Refreshed {updated_count} already-saved job(s)."
        if skipped_count:
            message += f" Skipped {skipped_count} result(s): {format_reason_code_counts(skipped_reason_code_counts(save_result.skipped))}."
        return message
    if skipped_count:
        reason_counts = skipped_reason_code_counts(save_result.skipped)
        if reason_counts.get("duplicate_for_user") == skipped_count:
            return f"I found {skipped_count} job(s) already in your Jobs list, so I did not add duplicates."
        return f"No new jobs were saved. I skipped {skipped_count} result(s): {format_reason_code_counts(skipped_reason_code_counts(save_result.skipped))}."
    if source_results:
        return "No new jobs were saved from the live source results."
    return "No live job results were found, so no jobs were saved."


def build_selected_job_discovery_assistant_message(
    selection_result: JobCandidateSelectionResult | None,
    save_result: JobDiscoverySaveResult,
    source_results: list[LiveJobSourceResult],
    all_skipped_results: list[SkippedJobResult] | None = None,
) -> str:
    all_skipped_results = all_skipped_results or save_result.skipped
    if selection_result is not None and selection_result.output.assistant_message:
        model_message = selection_assistant_message(selection_result)
        selected_count = len(selection_result.selected_entries)
        saved_count = len(save_result.saved_links)
        if model_message:
            if not saved_count and selected_count and save_result.skipped:
                return (
                    f"{model_message}\n\n"
                    f"None were newly saved after persistence: {format_reason_code_counts(skipped_reason_code_counts(save_result.skipped))}."
                )
            return model_message
        if selected_count and save_result.skipped:
            return (
                f"The model selected {selected_count} provider-backed job candidate(s), "
                f"but none were newly saved: {format_reason_code_counts(skipped_reason_code_counts(save_result.skipped))}."
            )
        if source_results:
            return NO_MODEL_SELECTION_EXPLANATION_FALLBACK
        if not selected_count and not saved_count:
            return NO_MODEL_SELECTION_EXPLANATION_FALLBACK
    if all_skipped_results:
        reason_counts = skipped_reason_code_counts(all_skipped_results)
        if reason_counts.get("duplicate_for_user") == len(all_skipped_results):
            return f"I found {len(all_skipped_results)} job(s) already in your Jobs list, so I did not add duplicates."
    return build_live_job_discovery_assistant_message(save_result, source_results)


def build_job_search_run_diagnostics(
    *,
    planner_result: JobSearchPlannerResult,
    selection_result: JobCandidateSelectionResult | None,
    assistant_message: str,
    replans_attempted: int,
    replan_limit: int,
    replanning_status: str,
    replan_decision: str,
    replan_reasons: list[str],
    replan_queries: list[str],
) -> dict[str, Any]:
    plan = planner_result.plan
    user_visible_summary = clean_user_facing_explanation(assistant_message, limit=900)
    return {
        "userVisibleSummary": user_visible_summary,
        "userSummary": user_visible_summary,
        "planner": {
            "rationale": clean_user_facing_explanation(plan.rationale, limit=900),
            "fallbackUsed": planner_result.fallback_used,
            "recentSearchesUsedCount": planner_result.recent_searches_used_count,
        },
        "selection": {
            "assistantMessage": selection_assistant_message(selection_result),
            "skippedCandidateNotes": selection_skipped_candidate_notes(selection_result),
            "clarifyingQuestions": selection_clarifying_questions(selection_result),
        },
        "replanning": {
            "replansAttempted": replans_attempted,
            "replanLimit": replan_limit,
            "replanningStatus": replanning_status,
            "replanningDecision": replan_decision,
            "replanReason": replan_reasons[-1] if replan_reasons else None,
            "replanReasons": clean_string_diagnostic_list(replan_reasons, limit=10, item_limit=160),
            "replanQueries": clean_string_diagnostic_list(replan_queries, limit=20, item_limit=240),
        },
    }


def selection_assistant_message(selection_result: JobCandidateSelectionResult | None) -> str | None:
    if selection_result is None or selection_result.response is None:
        return None
    message = clean_user_facing_explanation(selection_result.output.assistant_message, limit=900)
    if not message:
        return None
    if not selection_result.selected_entries and message == DEFAULT_SELECTION_ASSISTANT_MESSAGE:
        return None
    return message


def log_job_search_run_status_serialized(payload: dict[str, Any]) -> None:
    user_visible_summary = clean_user_facing_explanation(payload.get("userVisibleSummary"), limit=240)
    selection_message = clean_user_facing_explanation(payload.get("selectionAssistantMessage"), limit=240)
    logger.info(
        "Job search run status serialized: %s",
        json.dumps(
            {
                "runId": payload.get("id"),
                "status": payload.get("status"),
                "providerResultCount": payload.get("providerResultCount"),
                "candidatePoolCount": payload.get("candidatePoolCount"),
                "modelSelectedCount": payload.get("modelSelectedCount"),
                "savedCount": payload.get("savedCount"),
                "hasUserVisibleSummary": bool(user_visible_summary),
                "userVisibleSummaryPreview": user_visible_summary,
                "hasSelectionAssistantMessage": bool(selection_message),
                "selectionAssistantMessagePreview": selection_message,
                "plannerRationalePresent": bool(payload.get("plannerRationale")),
                "replansAttempted": payload.get("replansAttempted"),
                "replanningDecision": payload.get("replanningDecision"),
            },
            sort_keys=True,
            default=str,
        ),
    )


def selection_skipped_candidate_notes(selection_result: JobCandidateSelectionResult | None) -> list[dict[str, str]]:
    if selection_result is None or selection_result.response is None:
        return []
    notes: list[dict[str, str]] = []
    for note in selection_result.output.skipped_candidate_notes[:5]:
        candidate_id = clean_user_facing_explanation(note.candidate_id, limit=40)
        reason = clean_user_facing_explanation(note.reason, limit=300)
        if candidate_id and reason:
            notes.append({"candidateId": candidate_id, "reason": reason})
    return notes


def selection_clarifying_questions(selection_result: JobCandidateSelectionResult | None) -> list[str]:
    if selection_result is None or selection_result.response is None:
        return []
    return clean_string_diagnostic_list(selection_result.output.clarifying_questions, limit=3, item_limit=240)


def clean_user_facing_explanation(value: object, *, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split()).strip()
    if not cleaned:
        return None
    return safe_log_preview(cleaned, limit=limit)


def clean_string_diagnostic_list(values: list[str], *, limit: int, item_limit: int) -> list[str]:
    cleaned: list[str] = []
    for value in values[:limit]:
        item = clean_user_facing_explanation(value, limit=item_limit)
        if item:
            cleaned.append(item)
    return cleaned


def format_reason_code_counts(counts: dict[str, int]) -> str:
    return "; ".join(f"{count} {code}" for code, count in sorted(counts.items()))


def extract_http_urls(text: str) -> list[str]:
    return compact_unique_strings(re.findall(r"https?://[^\s<>)\"']+", text), limit=10)


def build_user_url_source_results(
    urls: list[str],
    *,
    search_request: JobSearchRequest,
) -> tuple[list[LiveJobSourceResult], list[ProviderDiagnostic], list[str]]:
    results: list[LiveJobSourceResult] = []
    diagnostics: list[ProviderDiagnostic] = []
    errors: list[str] = []
    for url in urls:
        greenhouse_result = build_greenhouse_user_url_source_result(url, search_request)
        if greenhouse_result is not None:
            results.append(greenhouse_result)
            diagnostics.append(
                ProviderDiagnostic(
                    provider_name="greenhouse",
                    provider_type="ats_board",
                    configured=True,
                    attempted=True,
                    result_count=1,
                    query="user-provided-url",
                    board_token=greenhouse_result.ats_board_token,
                    company_name=greenhouse_result.company_name,
                    search_mode="url",
                    reason="url_ingestion",
                )
            )
            continue
        domain = domain_from_url(url) or "Unknown company"
        results.append(
            LiveJobSourceResult(
                title="User-provided job posting",
                company_name=domain,
                job_url=url,
                source_provider="user_url",
                provider_type="broad_search",
                provenance="user_url",
                source_url=url,
                fit_summary="Saved from a user-provided job URL.",
            )
        )
    return results, diagnostics, errors


def build_greenhouse_user_url_source_result(url: str, search_request: JobSearchRequest) -> LiveJobSourceResult | None:
    from .providers.greenhouse import fetch_greenhouse_job_from_url, parse_greenhouse_url

    if parse_greenhouse_url(url) is None:
        return None
    try:
        return fetch_greenhouse_job_from_url(url, search_request)
    except Exception as error:
        logger.warning(
            "Greenhouse URL ingestion failed: %s",
            json.dumps({"error": type(error).__name__, "url": safe_log_preview(url, limit=200)}, sort_keys=True),
        )
        return None



def ensure_candidate_company_for_job(
    session: Session,
    *,
    candidate_profile_id: str,
    job: JobDiscoveryRecord,
    provider: str,
    discovery_query: str,
    ats_provider: str | None = None,
    ats_board_token: str | None = None,
) -> CompanyProfileLinkResult:
    normalized_name = normalize_company_name(job.company_name)
    company_urls = clean_company_source_urls(
        [job.company_website_url, job.company_careers_url, job.company_job_listings_url, *job.company_source_urls]
    )
    canonical = upsert_canonical_company(
        session,
        name=job.company_name.strip(),
        normalized_name=normalized_name or None,
        website_url=job.company_website_url,
        careers_url=job.company_careers_url,
        job_listings_url=job.company_job_listings_url,
        source_urls=company_urls[:12],
        source_summary=(
            "Company URL supplied by job discovery provider."
            if company_urls
            else "Company inferred from a provider-backed saved job; no canonical company URL was supplied."
        ),
        greenhouse_board_token=ats_board_token if ats_provider == "greenhouse" else None,
    )
    return ensure_candidate_company_link(
        session,
        candidate_profile_id=candidate_profile_id,
        company=canonical,
        review_status="new",
        derivation_status="model_derived",
        fit_reason=job.fit_summary,
        discovery_query=discovery_query,
        discovered_by=provider,
        personal_source_urls=clean_company_source_urls([job.job_url]),
    )



def get_owned_saved_job_or_404(session: Session, saved_job_id: str, candidate_profile_id: str) -> CandidateSavedJob:
    saved_job = session.scalar(
        select(CandidateSavedJob)
        .options(selectinload(CandidateSavedJob.job))
        .where(
            CandidateSavedJob.id == saved_job_id,
            CandidateSavedJob.candidate_profile_id == candidate_profile_id,
        )
    )
    if saved_job is None:
        raise HTTPException(status_code=404, detail="Saved job not found.")
    return saved_job


def load_application_lookup_for_saved_jobs(
    session: Session,
    links: list[CandidateSavedJob],
    candidate_profile_id: str,
) -> dict[str, Application]:
    job_ids = [link.job_id for link in links if link.job_id]
    if not job_ids:
        return {}
    applications = list(
        session.scalars(
            select(Application)
            .where(
                Application.candidate_profile_id == candidate_profile_id,
                Application.job_id.in_(job_ids),
            )
            .order_by(Application.created_at.desc())
        )
    )
    lookup: dict[str, Application] = {}
    for application in applications:
        if application.job_id and application.job_id not in lookup:
            lookup[application.job_id] = application
    return lookup


def get_application_for_saved_job(session: Session, saved_job: CandidateSavedJob, candidate_profile_id: str) -> Application | None:
    return session.scalar(
        select(Application)
        .where(
            Application.candidate_profile_id == candidate_profile_id,
            Application.job_id == saved_job.job_id,
        )
        .order_by(Application.created_at.desc())
        .limit(1)
    )


def saved_job_action_response(
    saved_job: CandidateSavedJob,
    *,
    application: Application | None,
    message: str,
    job_archived: bool = False,
    job_restored: bool = False,
    application_archived: bool = False,
    application_restored: bool = False,
    application_restore_skipped: bool = False,
) -> dict[str, Any]:
    return {
        "ok": True,
        "job_id": saved_job.job_id,
        "saved_job_id": saved_job.id,
        "job_archived": job_archived,
        "job_restored": job_restored,
        "application_id": application.id if application is not None else None,
        "application_archived": application_archived,
        "application_restored": application_restored,
        "application_restore_skipped": application_restore_skipped,
        "application_archived_by_action": application.archived_by_action if application is not None else None,
        "message": message,
        "job": serialize_saved_job(saved_job, application=application),
    }


def serialize_saved_job(link: CandidateSavedJob, *, application: Application | None = None) -> dict[str, Any]:
    job = link.job
    return {
        "id": link.id,
        "candidate_profile_id": link.candidate_profile_id,
        "job_id": link.job_id,
        "title": job.title,
        "company_name": job.company_name,
        "job_url": job.job_url,
        "canonical_url": job.canonical_url,
        "apply_url": job.apply_url,
        "source": job.source,
        "source_provider": job.source_provider,
        "provider_type": job.provider_type,
        "source_result_id": job.source_result_id,
        "source_query": job.source_query,
        "source_url": job.source_url,
        "source_updated_at": job.source_updated_at.isoformat() if job.source_updated_at else None,
        "company_website_url": job.company_website_url,
        "company_careers_url": job.company_careers_url,
        "ats_provider": job.ats_provider,
        "ats_board_token": job.ats_board_token,
        "provenance": job.provenance,
        "url_verification_status": job.url_verification_status,
        "url_verification_checked_at": job.url_verification_checked_at.isoformat() if job.url_verification_checked_at else None,
        "url_verification_summary": job.url_verification_summary,
        "location": job.location,
        "remote_work_mode": job.remote_work_mode,
        "employment_type": job.employment_type,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "salary_currency": job.salary_currency,
        "salary_text": job.salary_text,
        "full_description": job.full_description,
        "description_excerpt": job.description_excerpt,
        "fit_summary": link.fit_summary,
        "user_notes": link.user_notes,
        "status": link.status,
        "added_at": link.added_at.isoformat() if link.added_at else None,
        "archived_at": link.archived_at.isoformat() if link.archived_at else None,
        "archived_reason": link.archived_reason,
        "archived_by_action": link.archived_by_action,
        "has_application": application is not None,
        "application_id": application.id if application is not None else None,
        "application_status": application.status if application is not None else None,
        "application_archived_at": application.archived_at.isoformat() if application is not None and application.archived_at else None,
        "posting_date": job.posting_date.isoformat() if job.posting_date else None,
        "first_seen_at": job.first_seen_at.isoformat() if job.first_seen_at else None,
        "last_seen_at": job.last_seen_at.isoformat() if job.last_seen_at else None,
        "created_at": link.created_at.isoformat() if link.created_at else None,
        "updated_at": link.updated_at.isoformat() if link.updated_at else None,
    }


def normalize_job_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    query = [
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}
    ]
    normalized = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        path=parsed.path.rstrip("/") or "/",
        query=urlencode(query, doseq=True),
        fragment="",
    )
    return urlunparse(normalized)
