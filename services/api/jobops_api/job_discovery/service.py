from __future__ import annotations

import json
import logging
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
    serialize_current_saved_companies,
    should_prompt_for_discovery_targets,
)
from ..db.models import (
    Application,
    CandidateProfile,
    CandidateSavedJob,
    JobListing,
    JobSearchQueryRun,
    JobSearchRun,
)
from ..db.session import create_session_factory, get_db_session
from ..model_connector import ModelConnector, create_model_connector, read_model_connector_config_from_settings
from ..profiles import candidate_profile_to_private_context_dict, get_candidate_profile_by_slug
from ..security import require_internal_api_key
from ..settings import Settings, load_settings
from .models import (
    JobDiscoveryRequest,
    JobDiscoveryServiceResult,
    SavedJobActionResponse,
    SavedJobResponse,
)
from .candidate_discovery.models import CandidateDiscoveryResult
from .candidate_discovery.service import CandidateJobDiscoveryService, serialize_plan as serialize_db_backed_search_plan
from .candidate_discovery.diagnostics import format_candidate_discovery_diagnostics, infer_no_jobs_added_reason
from .candidate_discovery.statuses import HIDDEN_JOB_STATUSES
from .provider_utils import (
    clean_text_value,
    safe_log_preview,
)
ACTIVE_JOB_DISCOVERY_RUN_STATUSES = {"queued", "running", "started"}
TERMINAL_JOB_DISCOVERY_RUN_STATUSES = {"completed", "failed", "cancelled", "needs_confirmation"}
ACTIVE_JOB_DISCOVERY_RUN_STALE_AFTER = timedelta(hours=2)

router = APIRouter(prefix="/v1", tags=["jobs"], dependencies=[Depends(require_internal_api_key)])
logger = logging.getLogger(__name__)



@router.get("/jobs", response_model=list[SavedJobResponse])
def list_jobs(
    session: Session = Depends(get_db_session),
    auth: AuthContext = Depends(require_auth_context),
) -> list[dict[str, Any]]:
    latest_discovery_run_id = latest_completed_db_backed_job_search_run_id(session, auth.candidate_profile.id)
    statement = (
        select(CandidateSavedJob)
        .options(
            selectinload(CandidateSavedJob.job),
            selectinload(CandidateSavedJob.job_listing).selectinload(JobListing.sources),
        )
        .where(
            CandidateSavedJob.candidate_profile_id == auth.candidate_profile.id,
            CandidateSavedJob.status.not_in(HIDDEN_JOB_STATUSES),
        )
        .order_by(CandidateSavedJob.added_at.desc(), CandidateSavedJob.created_at.desc())
    )
    links = list(session.scalars(statement))
    application_by_saved_job_id = load_application_lookup_for_saved_jobs(session, links, auth.candidate_profile.id)
    return sort_serialized_saved_jobs(
        [
            serialize_saved_job(
                link,
                application=application_by_saved_job_id.get(link.id),
                highlighted_job_search_run_id=latest_discovery_run_id,
            )
            for link in links
        ]
    )


@router.get("/job-search-runs/latest")
def get_latest_job_search_run_status(
    session: Session = Depends(get_db_session),
    auth: AuthContext = Depends(require_auth_context),
) -> dict[str, Any]:
    run = session.scalar(
        select(JobSearchRun)
        .where(JobSearchRun.candidate_profile_id == auth.candidate_profile.id)
        .order_by(JobSearchRun.created_at.desc())
        .limit(1)
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
    payload = serialize_job_search_run_status(run, query_runs, session=session, candidate_profile_id=auth.candidate_profile.id)
    log_job_search_run_status_serialized(payload)
    return payload


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
    payload = serialize_job_search_run_status(run, query_runs, session=session, candidate_profile_id=auth.candidate_profile.id)
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

    active_connector = connector or create_model_connector(read_model_connector_config_from_settings(active_settings))
    discovery = CandidateJobDiscoveryService(
        session=db_session,
        settings=active_settings,
        connector=active_connector,
    ).run(
        request,
        candidate_profile=candidate_profile,
        current_saved_jobs=current_saved_jobs,
        current_saved_companies=current_saved_companies,
        target_context=target_context,
        private_profile_context=private_profile_context,
        job_search_run_id=job_search_run_id,
    )
    db_session.commit()
    return build_db_backed_job_discovery_result(
        discovery,
        current_saved_jobs=current_saved_jobs,
        current_saved_companies=current_saved_companies,
    )


def build_db_backed_job_discovery_result(
    discovery: CandidateDiscoveryResult,
    *,
    current_saved_jobs: list[dict[str, Any]],
    current_saved_companies: list[dict[str, Any]],
) -> JobDiscoveryServiceResult:
    diagnostics = discovery.diagnostics
    job_sync = diagnostics.get("jobSync") or {}
    database_queries = diagnostics.get("databaseQueries") or {}
    model_review = diagnostics.get("modelReview") or {}
    provider_names = sorted(
        {
            getattr(getattr(result, "request", None), "provider_name", None)
            or getattr(result, "provider_name", None)
            or "job_sync"
            for result in discovery.job_sync_results
        }
    )
    saved_jobs = [
        serialize_saved_job(link, highlighted_job_search_run_id=discovery.job_search_run_id)
        for link in discovery.selected_candidate_jobs
    ]
    recommended_jobs = [
        serialize_saved_job(link)
        for link in discovery.recommended_candidate_jobs
    ]
    updated_saved_jobs = [
        serialize_saved_job(link, highlighted_job_search_run_id=discovery.job_search_run_id)
        for link in discovery.updated_candidate_jobs
    ]
    no_jobs_added_reason = db_backed_no_jobs_added_reason(
        diagnostics,
        unique_job_pool_count=discovery.unique_job_pool_count,
        jobs_reviewed_count=discovery.jobs_reviewed_count,
        added_count=discovery.added_count,
    )
    job_sync_completed_count = diagnostic_int(job_sync.get("completedCount")) or sum(
        1 for row in job_sync.get("runs", []) if isinstance(row, dict) and row.get("status") == "completed"
    )
    database_matched_job_count = diagnostic_int(database_queries.get("uniqueJobPoolCount")) or discovery.unique_job_pool_count
    jobs_reviewed_by_model = diagnostic_int(model_review.get("jobsReviewedByModel")) or discovery.jobs_reviewed_count
    added_to_candidate_jobs_list = diagnostic_int(model_review.get("addedToCandidateJobsList")) or discovery.added_count
    recorded_model_rejections = diagnostic_int(model_review.get("recordedModelRejections")) or discovery.rejected_count
    model_review_completed = bool(model_review.get("modelReviewCompleted", True))
    selected_jobs_label = model_review.get("selectedJobsLabel") or "Added to jobs list"
    result_payload = {
        "assistantMessage": discovery.assistant_message,
        "userVisibleSummary": discovery.assistant_message,
        "userSummary": discovery.assistant_message,
        "jobs": recommended_jobs or saved_jobs,
        "updatedExistingJobs": updated_saved_jobs,
        "discoveredCount": discovery.unique_job_pool_count,
        "verifiedCount": 0,
        "savedCount": discovery.added_count,
        "updatedExistingCount": discovery.updated_count,
        "createdGlobalJobCount": 0,
        "updatedGlobalJobCount": 0,
        "duplicateCount": 0,
        "skippedCount": discovery.rejected_count,
        "skippedJobCount": discovery.rejected_count,
        "skippedJobs": [],
        "skippedReasons": model_review.get("rejectionReasonCounts") or {},
        "jobDiscoveryMode": "db_backed",
        "jobSearchRunId": discovery.job_search_run_id,
        "configuredProviders": provider_names,
        "providerDiagnostics": [],
        "diagnostics": diagnostics,
        "diagnosticMessages": format_candidate_discovery_diagnostics(diagnostics),
        "jobSyncCompletedCount": job_sync_completed_count,
        "jobSyncFailedCount": diagnostic_int(job_sync.get("failedCount")) or 0,
        "databaseMatchedJobCount": database_matched_job_count,
        "jobsReviewedByModel": jobs_reviewed_by_model,
        "modelReviewCompleted": model_review_completed,
        "modelReviewFailureReason": model_review.get("modelReviewFailureReason"),
        "addedToCandidateJobsList": added_to_candidate_jobs_list,
        "recommendedJobs": recommended_jobs,
        "recommendedJobIds": [job["id"] for job in recommended_jobs],
        "recommendedExistingJobCount": discovery.recommended_existing_count,
        "requestedRecommendationCount": discovery.requested_recommendation_count,
        "eligibleJobsListCount": discovery.eligible_jobs_list_count,
        "selectedJobsLabel": selected_jobs_label,
        "recordedModelRejections": recorded_model_rejections,
        "noJobsAddedReason": no_jobs_added_reason,
        "addedJobs": saved_jobs,
        "addedJobIds": [job["id"] for job in saved_jobs],
        "highlightedJobSearchRunId": discovery.job_search_run_id if saved_jobs else None,
        "searchPlan": serialize_db_backed_search_plan(discovery.search_plan),
        "searchCriteria": {
            "mode": discovery.search_plan.mode,
            "jobScope": discovery.search_plan.job_scope,
            "queryLabels": [query.label for query in discovery.search_plan.queries],
        },
        "recentSearchesUsed": 0,
        "plannerFallbackUsed": False,
        "plannerRationale": None,
        "plannerProvider": None,
        "plannerModel": None,
        "selectionAssistantMessage": discovery.assistant_message,
        "selectionSkippedCandidateNotes": [],
        "selectionClarifyingQuestions": [],
        "searchGroundingEnabled": False,
        "providerName": ",".join(provider_names) if provider_names else "job_sync",
        "sourceName": "synced_job_inventory",
        "searchQueriesUsed": [query.label for query in discovery.search_plan.queries],
        "providerResultCount": int(job_sync.get("rawResultCount") or 0),
        "providerRawResultCount": int(job_sync.get("rawResultCount") or 0),
        "totalMatchesReported": None,
        "pagesAttempted": None,
        "replansAttempted": 0,
        "replanLimit": 0,
        "replanningStatus": "not_applicable",
        "replanningDecision": None,
        "replanReason": None,
        "replanReasons": [],
        "replanQueries": [],
        "companiesSearched": [],
        "candidateCountAfterProviderNormalization": discovery.unique_job_pool_count,
        "candidateCountAfterDedupe": discovery.unique_job_pool_count,
        "candidateCountAfterHardExclusionFilter": discovery.unique_job_pool_count,
        "candidateCountAfterDiversityCap": discovery.unique_job_pool_count,
        "candidateCountSentToModel": jobs_reviewed_by_model,
        "modelSelectedCount": discovery.added_count,
        "selectedCandidateIds": [],
        "invalidSelectedCandidateIds": [],
        "savedJobIds": [job["id"] for job in saved_jobs],
        "trimmedByCompanyCapCount": 0,
        "trimmedByProviderCapCount": 0,
        "verifiedUrlCount": 0,
        "savedJobCount": discovery.added_count,
        "currentSavedJobCount": len(current_saved_jobs),
        "excludedJobUrlCount": len(current_saved_job_urls(current_saved_jobs)),
        "currentSavedCompanyCount": len(current_saved_companies),
        "databaseQueryCount": len(database_queries.get("queries", [])) if isinstance(database_queries.get("queries"), list) else 0,
    }
    return JobDiscoveryServiceResult(body={"ok": True, "result": result_payload}, status_code=200)


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
                    complete_job_search_run(refreshed_run, status="completed")
                else:
                    complete_job_search_run(
                        refreshed_run,
                        status="failed",
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


def latest_completed_db_backed_job_search_run_id(session: Session, candidate_profile_id: str) -> str | None:
    return session.scalar(
        select(JobSearchRun.id)
        .where(
            JobSearchRun.candidate_profile_id == candidate_profile_id,
            JobSearchRun.search_mode == "db_backed",
            JobSearchRun.status == "completed",
        )
        .order_by(JobSearchRun.completed_at.desc(), JobSearchRun.created_at.desc())
        .limit(1)
    )


def load_added_jobs_for_search_run(session: Session, run_id: str, candidate_profile_id: str) -> list[dict[str, Any]]:
    statement = (
        select(CandidateSavedJob)
        .options(
            selectinload(CandidateSavedJob.job),
            selectinload(CandidateSavedJob.job_listing).selectinload(JobListing.sources),
        )
        .where(
            CandidateSavedJob.candidate_profile_id == candidate_profile_id,
            CandidateSavedJob.job_search_run_id == run_id,
            CandidateSavedJob.status.not_in(HIDDEN_JOB_STATUSES),
        )
        .order_by(CandidateSavedJob.added_at.desc(), CandidateSavedJob.created_at.desc())
    )
    links = list(session.scalars(statement))
    application_by_saved_job_id = load_application_lookup_for_saved_jobs(session, links, candidate_profile_id)
    return [
        serialize_saved_job(link, application=application_by_saved_job_id.get(link.id), highlighted_job_search_run_id=run_id)
        for link in links
    ]


def load_saved_jobs_by_ids(session: Session, saved_job_ids: list[str], candidate_profile_id: str) -> list[dict[str, Any]]:
    order = {saved_job_id: index for index, saved_job_id in enumerate(saved_job_ids)}
    if not order:
        return []
    links = list(
        session.scalars(
            select(CandidateSavedJob)
            .options(
                selectinload(CandidateSavedJob.job),
                selectinload(CandidateSavedJob.job_listing).selectinload(JobListing.sources),
            )
            .where(
                CandidateSavedJob.candidate_profile_id == candidate_profile_id,
                CandidateSavedJob.id.in_(order),
                CandidateSavedJob.status.not_in(HIDDEN_JOB_STATUSES),
            )
        )
    )
    application_by_saved_job_id = load_application_lookup_for_saved_jobs(session, links, candidate_profile_id)
    return [
        serialize_saved_job(link, application=application_by_saved_job_id.get(link.id))
        for link in sorted(links, key=lambda item: order.get(item.id, len(order)))
    ]


def sort_serialized_saved_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    newest_first = sorted(jobs, key=lambda job: str(job.get("added_at") or job.get("updated_at") or ""), reverse=True)
    return sorted(newest_first, key=lambda job: 0 if job.get("highlighted") or job.get("justAdded") else 1)


def db_backed_no_jobs_added_reason(
    diagnostics: dict[str, Any],
    *,
    unique_job_pool_count: int,
    jobs_reviewed_count: int,
    added_count: int,
) -> str | None:
    stored_reason = diagnostics.get("noJobsAddedReason")
    if isinstance(stored_reason, str) and stored_reason:
        return stored_reason
    model_review = diagnostics.get("modelReview") if isinstance(diagnostics.get("modelReview"), dict) else {}
    return infer_no_jobs_added_reason(
        unique_job_pool_count=diagnostic_int(model_review.get("uniqueJobsInPool")) or unique_job_pool_count,
        jobs_reviewed_count=diagnostic_int(model_review.get("jobsReviewedByModel")) or jobs_reviewed_count,
        added_count=diagnostic_int(model_review.get("addedToCandidateJobsList")) or added_count,
        model_review_completed=model_review.get("modelReviewCompleted", True),
        model_review_fallback=bool(model_review.get("modelReviewFallback")),
        review_validation=model_review.get("reviewValidation"),
    )


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


def serialize_job_search_run_status(
    run: JobSearchRun,
    query_runs: list[JobSearchQueryRun],
    *,
    session: Session | None = None,
    candidate_profile_id: str | None = None,
) -> dict[str, Any]:
    provider_error_count = run.provider_error_count or sum(1 for query in query_runs if query.error)
    diagnostics = run.run_diagnostics_json if isinstance(run.run_diagnostics_json, dict) else {}
    planner = diagnostics.get("planner") if isinstance(diagnostics.get("planner"), dict) else {}
    selection = diagnostics.get("selection") if isinstance(diagnostics.get("selection"), dict) else {}
    replanning = diagnostics.get("replanning") if isinstance(diagnostics.get("replanning"), dict) else {}
    model_review = diagnostics.get("modelReview") if isinstance(diagnostics.get("modelReview"), dict) else {}
    is_db_backed_run = run.search_mode == "db_backed" or "jobSync" in diagnostics or "databaseQueries" in diagnostics
    added_jobs = load_added_jobs_for_search_run(session, run.id, candidate_profile_id) if session is not None and candidate_profile_id else []
    recommended_job_ids = [
        str(item) for item in diagnostics.get("recommendedJobIds", []) if isinstance(item, str)
    ]
    recommended_jobs = (
        load_saved_jobs_by_ids(session, recommended_job_ids, candidate_profile_id)
        if session is not None and candidate_profile_id and recommended_job_ids
        else []
    )
    added_job_ids = [job["id"] for job in added_jobs] or [
        str(item) for item in diagnostics.get("addedJobIds", []) if isinstance(item, str)
    ]
    no_jobs_added_reason = (
        db_backed_no_jobs_added_reason(
            diagnostics,
            unique_job_pool_count=run.candidate_pool_count,
            jobs_reviewed_count=run.candidate_pool_count,
            added_count=run.saved_count,
        )
        if is_db_backed_run
        else None
    )
    status_payload = {
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
        "jobDiscoveryMode": run.search_mode,
        "diagnosticMessages": format_candidate_discovery_diagnostics(diagnostics) if is_db_backed_run else None,
        "modelReviewCompleted": model_review.get("modelReviewCompleted", True) if is_db_backed_run else None,
        "modelReviewFailureReason": clean_user_facing_explanation(model_review.get("modelReviewFailureReason"), limit=240),
        "selectedJobsLabel": clean_user_facing_explanation(model_review.get("selectedJobsLabel"), limit=120),
        "noJobsAddedReason": no_jobs_added_reason,
        "addedJobs": added_jobs,
        "addedJobIds": added_job_ids,
        "recommendedJobs": recommended_jobs,
        "recommendedJobIds": recommended_job_ids,
        "recommendedExistingJobCount": model_review.get("recommendedExistingJobCount"),
        "requestedRecommendationCount": model_review.get("requestedRecommendationCount"),
        "eligibleJobsListCount": model_review.get("eligibleJobsListCount"),
        "highlightedJobSearchRunId": run.id if is_db_backed_run and run.status == "completed" and added_jobs else None,
    }
    status_payload["diagnostics"] = build_serialized_job_search_run_diagnostics(
        run,
        query_runs,
        status_payload=status_payload,
        stored_diagnostics=diagnostics,
    )
    return status_payload


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
        diagnostics = run.run_diagnostics_json if isinstance(run.run_diagnostics_json, dict) else {}
        if diagnostics.get("noJobsAddedReason") == "model_planning_failed":
            return "Model search planning did not complete, so JobOps did not run Job Sync, database search, or job review."
        return "Job discovery failed. No browser replay was attempted."
    if provider_error_count:
        return f"Job discovery finished with {provider_error_count} provider error(s)."
    return f"Job discovery status: {run.status}."


def build_serialized_job_search_run_diagnostics(
    run: JobSearchRun,
    query_runs: list[JobSearchQueryRun],
    *,
    status_payload: dict[str, Any],
    stored_diagnostics: dict[str, Any],
) -> dict[str, Any]:
    if "jobSync" in stored_diagnostics or "databaseQueries" in stored_diagnostics:
        return sanitize_db_backed_run_diagnostics(stored_diagnostics, status_payload=status_payload, run=run)
    provider_diagnostics = stored_diagnostics.get("providerDiagnostics")
    provider_rows = (
        sanitize_provider_diagnostics_for_status(provider_diagnostics)
        if isinstance(provider_diagnostics, list)
        else provider_diagnostics_from_query_runs(query_runs)
    )
    replanning = status_payload_replanning(status_payload, provider_rows, run)
    return {
        "searchCriteria": build_status_search_criteria(run.search_plan_json if isinstance(run.search_plan_json, dict) else {}),
        "providerDiagnostics": provider_rows,
        "modelReview": {
            "candidateCountAfterDedupe": run.candidate_count_after_dedupe,
            "candidatePoolCount": run.candidate_pool_count,
            "modelSelectedCount": run.model_selected_count,
            "savedCount": run.saved_count,
            "updatedExistingCount": run.updated_existing_count,
            "duplicateCount": run.duplicate_count,
            "skippedCount": run.skipped_count,
            "providerErrorCount": status_payload.get("providerErrorCount", run.provider_error_count),
        },
        "modelExplanation": {
            "userVisibleSummary": status_payload.get("userVisibleSummary"),
            "userSummary": status_payload.get("userSummary"),
            "plannerRationale": status_payload.get("plannerRationale"),
            "selectionAssistantMessage": status_payload.get("selectionAssistantMessage"),
            "skippedCandidateNotes": status_payload.get("selectionSkippedCandidateNotes") or [],
        },
        "replanning": replanning,
    }


def sanitize_db_backed_run_diagnostics(
    stored_diagnostics: dict[str, Any],
    *,
    status_payload: dict[str, Any],
    run: JobSearchRun,
) -> dict[str, Any]:
    job_sync = stored_diagnostics.get("jobSync") if isinstance(stored_diagnostics.get("jobSync"), dict) else {}
    database_queries = (
        stored_diagnostics.get("databaseQueries") if isinstance(stored_diagnostics.get("databaseQueries"), dict) else {}
    )
    model_review = stored_diagnostics.get("modelReview") if isinstance(stored_diagnostics.get("modelReview"), dict) else {}
    return {
        "planner": sanitize_db_backed_planner_diagnostics(stored_diagnostics.get("planner")),
        "jobSync": {
            "runs": sanitize_db_backed_sync_rows(job_sync.get("runs")),
            "runCount": diagnostic_int(job_sync.get("runCount")) or 0,
            "rawResultCount": diagnostic_int(job_sync.get("rawResultCount")) or 0,
            "normalizedCount": diagnostic_int(job_sync.get("normalizedCount")) or 0,
            "createdCount": diagnostic_int(job_sync.get("createdCount")) or 0,
            "updatedCount": diagnostic_int(job_sync.get("updatedCount")) or 0,
            "completedCount": diagnostic_int(job_sync.get("completedCount")) or 0,
            "failedCount": diagnostic_int(job_sync.get("failedCount")) or 0,
        },
        "databaseQueries": {
            "queries": sanitize_db_backed_query_rows(database_queries.get("queries")),
            "uniqueJobPoolCount": diagnostic_int(database_queries.get("uniqueJobPoolCount")) or run.candidate_pool_count,
            "totalRowsMatched": diagnostic_int(database_queries.get("totalRowsMatched")) or 0,
        },
        "modelReview": {
            "uniqueJobsInPool": diagnostic_int(model_review.get("uniqueJobsInPool")) or run.candidate_pool_count,
            "jobsReviewedByModel": diagnostic_int(model_review.get("jobsReviewedByModel")) or run.candidate_pool_count,
            "addedToCandidateJobsList": diagnostic_int(model_review.get("addedToCandidateJobsList")) or run.saved_count,
            "recordedModelRejections": diagnostic_int(model_review.get("recordedModelRejections")) or run.skipped_count,
            "selectedJobsLabel": clean_user_facing_explanation(model_review.get("selectedJobsLabel"), limit=120),
            "topRejectionReasonCounts": model_review.get("topRejectionReasonCounts") if isinstance(model_review.get("topRejectionReasonCounts"), dict) else {},
            "rejectionReasonCounts": model_review.get("rejectionReasonCounts") if isinstance(model_review.get("rejectionReasonCounts"), dict) else {},
            "modelReviewCompleted": model_review.get("modelReviewCompleted", True),
            "modelReviewFallback": bool(model_review.get("modelReviewFallback")),
            "modelReviewFailureReason": clean_user_facing_explanation(model_review.get("modelReviewFailureReason"), limit=240),
            "reviewValidation": model_review.get("reviewValidation") if isinstance(model_review.get("reviewValidation"), dict) else {},
        },
        "noJobsAddedReason": status_payload.get("noJobsAddedReason") or stored_diagnostics.get("noJobsAddedReason"),
    }


def sanitize_db_backed_planner_diagnostics(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "status": clean_user_facing_explanation(value.get("status"), limit=80),
        "modelUsed": bool(value.get("modelUsed")),
        "planningFailed": bool(value.get("planningFailed")),
        "error": clean_user_facing_explanation(value.get("error"), limit=240),
        "errorDetail": clean_user_facing_explanation(value.get("errorDetail"), limit=240),
        "mode": clean_user_facing_explanation(value.get("mode"), limit=80),
        "modeRationale": clean_user_facing_explanation(value.get("modeRationale"), limit=360),
        "jobScope": clean_user_facing_explanation(value.get("jobScope"), limit=80),
        "syncPlanRationale": clean_user_facing_explanation(value.get("syncPlanRationale"), limit=360),
        "useFollowedCompanyBoards": bool(value.get("useFollowedCompanyBoards")),
        "plannerAttemptCount": diagnostic_int(value.get("plannerAttemptCount")) or 0,
        "criticAttemptCount": diagnostic_int(value.get("criticAttemptCount")) or 0,
        "rejectedPlans": sanitize_rejected_plan_rows(value.get("rejectedPlans")),
        "finalPlanStatus": clean_user_facing_explanation(value.get("finalPlanStatus"), limit=80),
        "resultReplanCount": diagnostic_int(value.get("resultReplanCount")) or 0,
        "resultReplanReason": clean_user_facing_explanation(value.get("resultReplanReason"), limit=120),
        "plannedSyncSignatures": sanitize_planner_signature_rows(value.get("plannedSyncSignatures")),
        "existingSyncSignaturesSelected": sanitize_planner_signature_rows(value.get("existingSyncSignaturesSelected")),
        "plannedDbQueries": sanitize_planner_query_rows(value.get("plannedDbQueries")),
    }


def sanitize_rejected_plan_rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in value[:10]:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "issueCode": clean_user_facing_explanation(item.get("issueCode"), limit=80),
                "issueMessage": clean_user_facing_explanation(item.get("issueMessage"), limit=240),
                "mode": clean_user_facing_explanation(item.get("mode"), limit=80),
                "modeRationale": clean_user_facing_explanation(item.get("modeRationale"), limit=240),
            }
        )
    return rows


def sanitize_planner_signature_rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in value[:100]:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "id": clean_user_facing_explanation(item.get("id"), limit=80),
                "syncKey": clean_user_facing_explanation(item.get("syncKey"), limit=240),
                "providerName": clean_user_facing_explanation(item.get("providerName"), limit=80),
                "queryText": clean_user_facing_explanation(item.get("queryText"), limit=160),
                "queryKind": clean_user_facing_explanation(item.get("queryKind"), limit=80),
                "displayLocation": clean_user_facing_explanation(item.get("displayLocation"), limit=160),
                "providerCountry": clean_user_facing_explanation(item.get("providerCountry"), limit=20),
                "providerWhere": clean_user_facing_explanation(item.get("providerWhere"), limit=160),
                "maxPages": diagnostic_int(item.get("maxPages")),
                "resultsPerPage": diagnostic_int(item.get("resultsPerPage")),
                "enabled": bool(item.get("enabled")),
                "verificationStatus": clean_user_facing_explanation(item.get("verificationStatus"), limit=80),
                "action": clean_user_facing_explanation(item.get("action"), limit=80),
                "syncRunStatus": clean_user_facing_explanation(item.get("syncRunStatus"), limit=80),
                "raw": diagnostic_int(item.get("raw")),
                "normalized": diagnostic_int(item.get("normalized")),
                "created": diagnostic_int(item.get("created")),
                "updated": diagnostic_int(item.get("updated")),
            }
        )
    return rows


def sanitize_planner_query_rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in value[:100]:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "label": clean_user_facing_explanation(item.get("label"), limit=240),
                "titleTermsAny": clean_string_diagnostic_list(coerce_diagnostic_string_list(item.get("titleTermsAny")), limit=20, item_limit=120),
                "titleTermsAll": clean_string_diagnostic_list(coerce_diagnostic_string_list(item.get("titleTermsAll")), limit=20, item_limit=120),
                "titleTermsExclude": clean_string_diagnostic_list(coerce_diagnostic_string_list(item.get("titleTermsExclude")), limit=20, item_limit=120),
                "descriptionTermsAny": clean_string_diagnostic_list(coerce_diagnostic_string_list(item.get("descriptionTermsAny")), limit=20, item_limit=120),
                "descriptionTermsAll": clean_string_diagnostic_list(coerce_diagnostic_string_list(item.get("descriptionTermsAll")), limit=20, item_limit=120),
                "descriptionTermsExclude": clean_string_diagnostic_list(coerce_diagnostic_string_list(item.get("descriptionTermsExclude")), limit=20, item_limit=120),
                "companyNamesAny": clean_string_diagnostic_list(coerce_diagnostic_string_list(item.get("companyNamesAny")), limit=20, item_limit=120),
                "companyNamesExclude": clean_string_diagnostic_list(coerce_diagnostic_string_list(item.get("companyNamesExclude")), limit=20, item_limit=120),
                "sourceProvidersAny": clean_string_diagnostic_list(coerce_diagnostic_string_list(item.get("sourceProvidersAny")), limit=10, item_limit=80),
                "atsBoardTokensAny": clean_string_diagnostic_list(coerce_diagnostic_string_list(item.get("atsBoardTokensAny")), limit=20, item_limit=120),
                "locationCountriesAny": clean_string_diagnostic_list(coerce_diagnostic_string_list(item.get("locationCountriesAny")), limit=10, item_limit=40),
                "locationRegionsAny": clean_string_diagnostic_list(coerce_diagnostic_string_list(item.get("locationRegionsAny")), limit=10, item_limit=80),
                "locationCitiesAny": clean_string_diagnostic_list(coerce_diagnostic_string_list(item.get("locationCitiesAny")), limit=10, item_limit=80),
                "locationMetrosAny": clean_string_diagnostic_list(coerce_diagnostic_string_list(item.get("locationMetrosAny")), limit=10, item_limit=80),
                "locationDisplayTermsAny": clean_string_diagnostic_list(coerce_diagnostic_string_list(item.get("locationDisplayTermsAny")), limit=10, item_limit=120),
                "remoteWorkModesAny": clean_string_diagnostic_list(coerce_diagnostic_string_list(item.get("remoteWorkModesAny")), limit=10, item_limit=80),
                "employmentTypesAny": clean_string_diagnostic_list(coerce_diagnostic_string_list(item.get("employmentTypesAny")), limit=10, item_limit=80),
                "salaryCurrency": clean_user_facing_explanation(item.get("salaryCurrency"), limit=20),
                "salaryMinAtLeast": diagnostic_int(item.get("salaryMinAtLeast")),
                "sourceStatusesAny": clean_string_diagnostic_list(coerce_diagnostic_string_list(item.get("sourceStatusesAny")), limit=10, item_limit=80),
                "freshnessDays": diagnostic_int(item.get("freshnessDays")),
                "limit": diagnostic_int(item.get("limit")),
                "activeOnly": bool(item.get("activeOnly")),
                "includeModelRejected": bool(item.get("includeModelRejected")),
                "orderBy": clean_user_facing_explanation(item.get("orderBy"), limit=80),
            }
        )
    return rows


def sanitize_db_backed_sync_rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in value[:200]:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "syncKey": clean_user_facing_explanation(item.get("syncKey"), limit=240),
                "status": clean_user_facing_explanation(item.get("status"), limit=80),
                "raw": diagnostic_int(item.get("raw")) or 0,
                "normalized": diagnostic_int(item.get("normalized")) or 0,
                "created": diagnostic_int(item.get("created")) or 0,
                "updated": diagnostic_int(item.get("updated")) or 0,
                "failed": diagnostic_int(item.get("failed")) or None,
            }
        )
    return rows


def sanitize_db_backed_query_rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in value[:200]:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "label": clean_user_facing_explanation(item.get("label"), limit=240),
                "jobCount": diagnostic_int(item.get("jobCount")) or 0,
            }
        )
    return rows


def build_status_search_criteria(search_plan: dict[str, Any]) -> dict[str, Any]:
    strategy = search_plan.get("providerStrategy") if isinstance(search_plan.get("providerStrategy"), dict) else {}
    return {
        "searchMode": clean_user_facing_explanation(search_plan.get("searchMode") or search_plan.get("search_mode"), limit=80),
        "roleQueries": clean_string_diagnostic_list(coerce_diagnostic_string_list(search_plan.get("roleQueries") or search_plan.get("role_queries")), limit=12, item_limit=160),
        "companyNames": clean_string_diagnostic_list(coerce_diagnostic_string_list(search_plan.get("companyNames") or search_plan.get("company_names")), limit=50, item_limit=180),
        "locations": clean_string_diagnostic_list(coerce_diagnostic_string_list(search_plan.get("locations")), limit=12, item_limit=120),
        "remoteWorkModes": clean_string_diagnostic_list(coerce_diagnostic_string_list(search_plan.get("remoteWorkModes") or search_plan.get("remote_work_modes")), limit=5, item_limit=80),
        "salaryMin": search_plan.get("salaryMin") if isinstance(search_plan.get("salaryMin"), int) else None,
        "excludeTerms": clean_string_diagnostic_list(coerce_diagnostic_string_list(search_plan.get("excludeTerms") or search_plan.get("exclude_terms")), limit=20, item_limit=120),
        "maxProviderPages": strategy.get("maxProviderPages") if isinstance(strategy.get("maxProviderPages"), int) else None,
    }


def sanitize_provider_diagnostics_for_status(values: list[object]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in values[:200]:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "providerName": clean_user_facing_explanation(item.get("providerName") or item.get("provider_name"), limit=120),
                "providerType": clean_user_facing_explanation(item.get("providerType") or item.get("provider_type"), limit=80),
                "companyName": clean_user_facing_explanation(item.get("companyName") or item.get("company_name"), limit=240),
                "boardToken": clean_user_facing_explanation(item.get("boardToken") or item.get("board_token"), limit=120),
                "attempted": bool(item.get("attempted")),
                "configured": bool(item.get("configured")),
                "queryPreview": clean_user_facing_explanation(item.get("query"), limit=180),
                "requestCriteria": sanitize_request_criteria(item.get("requestCriteria") or item.get("request_criteria")),
                "rawResultCount": diagnostic_int(item.get("rawResultCount")),
                "resultCount": diagnostic_int(item.get("resultCount")) or 0,
                "normalizedResultCount": diagnostic_int(item.get("normalizedResultCount")),
                "dedupedResultCount": diagnostic_int(item.get("dedupedResultCount")),
                "candidateCountAfterFilters": diagnostic_int(item.get("candidateCountAfterFilters")),
                "totalMatches": diagnostic_int(item.get("totalMatches")),
                "page": diagnostic_int(item.get("page")),
                "pagesAttempted": diagnostic_int(item.get("pagesAttempted")),
                "errorSummary": clean_user_facing_explanation(item.get("error"), limit=240),
                "searchMode": clean_user_facing_explanation(item.get("searchMode") or item.get("search_mode"), limit=120),
                "reason": clean_user_facing_explanation(item.get("reason"), limit=160),
            }
        )
    return rows


def provider_diagnostics_from_query_runs(query_runs: list[JobSearchQueryRun]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for query in query_runs[:200]:
        rows.append(
            {
                "providerName": query.provider_name,
                "providerType": provider_type_for_name(query.provider_name),
                "companyName": query.company_name,
                "boardToken": None,
                "attempted": True,
                "configured": True,
                "queryPreview": safe_log_preview(query.query or "", limit=180) or None,
                "requestCriteria": None,
                "rawResultCount": query.raw_result_count,
                "resultCount": query.normalized_result_count,
                "normalizedResultCount": query.normalized_result_count,
                "dedupedResultCount": query.deduped_result_count,
                "candidateCountAfterFilters": query.candidate_count_after_filters,
                "totalMatches": query.total_matches,
                "page": query.page,
                "pagesAttempted": None,
                "errorSummary": safe_log_preview(query.error or "", limit=240) or None,
                "searchMode": None,
                "reason": None,
            }
        )
    return rows


def sanitize_request_criteria(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    safe: dict[str, Any] = {}
    for key, item in value.items():
        key_text = clean_user_facing_explanation(str(key), limit=80)
        if not key_text or is_sensitive_diagnostic_key(key_text):
            continue
        if isinstance(item, (str, int, float, bool)) or item is None:
            safe[key_text] = clean_user_facing_explanation(item, limit=180) if isinstance(item, str) else item
    return safe or None


def diagnostic_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def is_sensitive_diagnostic_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    if normalized in {"app_id", "app_key", "api_key", "authorization", "cookie", "key", "password", "secret", "token"}:
        return True
    return any(marker in normalized for marker in ("_secret", "_token", "_cookie", "_password", "_api_key", "_app_key"))


def status_payload_replanning(
    status_payload: dict[str, Any],
    provider_rows: list[dict[str, Any]],
    run: JobSearchRun,
) -> dict[str, Any]:
    reasons = status_payload.get("replanReasons") if isinstance(status_payload.get("replanReasons"), list) else []
    decision = clean_user_facing_explanation(status_payload.get("replanningDecision"), limit=160)
    display = build_replanning_display(provider_rows, reasons, decision, run)
    return {
        "replansAttempted": status_payload.get("replansAttempted"),
        "replanLimit": status_payload.get("replanLimit"),
        "replanReasons": clean_string_diagnostic_list(coerce_diagnostic_string_list(reasons), limit=10, item_limit=160),
        "replanningDecision": decision,
        "replanQueries": status_payload.get("replanQueries") if isinstance(status_payload.get("replanQueries"), list) else [],
        "displayLabel": display["label"],
        "displayMessage": display["message"],
        "triggerProviderName": display["providerName"],
        "triggerProviderType": display["providerType"],
        "companyBoardsReturnedCandidates": display["companyBoardsReturnedCandidates"],
        "providerResultsExisted": run.total_provider_results > 0,
        "candidatePoolExisted": run.candidate_pool_count > 0 or run.candidate_count_after_dedupe > 0,
    }


def build_replanning_display(
    provider_rows: list[dict[str, Any]],
    reasons: list[object],
    decision: str | None,
    run: JobSearchRun,
) -> dict[str, Any]:
    reason_texts = [str(reason) for reason in reasons if str(reason)]
    primary_reason = reason_texts[-1] if reason_texts else (decision.split(":", 1)[1] if decision and ":" in decision else None)
    zero_match_row = next((row for row in provider_rows if row.get("totalMatches") == 0), None)
    board_candidates = any(row.get("providerType") == "ats_board" and int(row.get("resultCount") or 0) > 0 for row in provider_rows)
    if primary_reason == "zero_total_matches":
        provider_name = clean_user_facing_explanation((zero_match_row or {}).get("providerName"), limit=120)
        provider_type = clean_user_facing_explanation((zero_match_row or {}).get("providerType"), limit=80)
        if board_candidates:
            label = "Provider-reported zero total matches"
            if provider_type == "broad_search" or provider_name:
                label = "Broad search reported 0 total matches"
            message = (
                "Broad search reported 0 total matches, while company board searches returned candidates."
                if provider_type == "broad_search" or not provider_name
                else f"{provider_name} reported 0 total matches, while company board searches returned candidates."
            )
        elif run.total_provider_results > 0:
            label = "Provider-reported zero total matches"
            message = (
                f"{provider_name or 'A provider'} reported 0 total matches, but other provider results existed."
            )
        else:
            label = "All searched providers reported 0 total matches"
            message = "Replan triggered because searched providers reported 0 total matches."
        return {
            "label": label,
            "message": message,
            "providerName": provider_name or "unknown",
            "providerType": provider_type or "unknown",
            "companyBoardsReturnedCandidates": board_candidates,
        }
    if primary_reason:
        return {
            "label": format_replan_reason_label(primary_reason),
            "message": f"Replan decision: {format_replan_reason_label(primary_reason)}.",
            "providerName": clean_user_facing_explanation((zero_match_row or {}).get("providerName"), limit=120) or "unknown",
            "providerType": clean_user_facing_explanation((zero_match_row or {}).get("providerType"), limit=80) or "unknown",
            "companyBoardsReturnedCandidates": board_candidates,
        }
    return {
        "label": "No replanning needed",
        "message": "No replanning was needed for this run.",
        "providerName": "unknown",
        "providerType": "unknown",
        "companyBoardsReturnedCandidates": board_candidates,
    }


def format_replan_reason_label(reason: str) -> str:
    return reason.replace("_", " ").capitalize()


def coerce_diagnostic_string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value]
    return []


def get_existing_job_search_run(session: Session, run_id: str | None, candidate_profile_id: str) -> JobSearchRun | None:
    if not run_id:
        return None
    return session.scalar(
        select(JobSearchRun).where(
            JobSearchRun.id == run_id,
            JobSearchRun.candidate_profile_id == candidate_profile_id,
        )
    )


def complete_job_search_run(
    run: JobSearchRun,
    *,
    status: str,
    total_provider_results: int = 0,
    total_matches_reported: int | None = None,
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
    run.total_matches_reported = total_matches_reported
    run.candidate_pool_count = candidate_pool_count
    run.candidate_count_after_dedupe = candidate_count_after_dedupe
    run.replans_attempted = replans_attempted
    run.model_selected_count = model_selected_count
    run.saved_count = saved_count
    run.updated_existing_count = updated_existing_count
    run.duplicate_count = duplicate_count
    run.skipped_count = skipped_count
    run.provider_error_count = provider_error_count or 0
    run.error = error
    if run_diagnostics is not None:
        run.run_diagnostics_json = run_diagnostics
    run.started_at = run.started_at or datetime.now(timezone.utc)
    run.completed_at = datetime.now(timezone.utc)


def serialize_current_saved_jobs(session: Session, candidate_profile_id: str) -> list[dict[str, Any]]:
    links = list(
        session.scalars(
            select(CandidateSavedJob)
            .options(
                selectinload(CandidateSavedJob.job),
                selectinload(CandidateSavedJob.job_listing).selectinload(JobListing.sources),
            )
            .where(
                CandidateSavedJob.candidate_profile_id == candidate_profile_id,
                CandidateSavedJob.status.not_in(HIDDEN_JOB_STATUSES),
            )
            .order_by(CandidateSavedJob.added_at.desc())
            .limit(50)
        )
    )
    serialized: list[dict[str, Any]] = []
    for link in links:
        if link.job is not None:
            serialized.append({
                "saved_job_id": link.id,
                "job_id": link.job.id,
                "job_listing_id": None,
                "title": link.job.title,
                "company_name": link.job.company_name,
                "job_url": link.job.job_url,
                "normalized_url": link.job.normalized_url,
                "status": link.status,
                "added_at": link.added_at.isoformat() if link.added_at else None,
            })
        elif link.job_listing is not None:
            job_listing_url = job_listing_primary_url(link.job_listing)
            serialized.append({
                "saved_job_id": link.id,
                "job_id": None,
                "job_listing_id": link.job_listing.id,
                "title": link.job_listing.title,
                "company_name": link.job_listing.company_name,
                "job_url": job_listing_url,
                "normalized_url": normalize_job_url(job_listing_url),
                "status": link.status,
                "added_at": link.added_at.isoformat() if link.added_at else None,
            })
    return serialized


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


def get_owned_saved_job_or_404(session: Session, saved_job_id: str, candidate_profile_id: str) -> CandidateSavedJob:
    saved_job = session.scalar(
        select(CandidateSavedJob)
        .options(
            selectinload(CandidateSavedJob.job),
            selectinload(CandidateSavedJob.job_listing).selectinload(JobListing.sources),
        )
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
    saved_job_ids = [link.id for link in links]
    job_id_to_saved_job_id = {link.job_id: link.id for link in links if link.job_id}
    if not saved_job_ids and not job_id_to_saved_job_id:
        return {}
    lookup: dict[str, Application] = {}
    if saved_job_ids:
        applications_by_saved_job = list(
            session.scalars(
                select(Application)
                .where(
                    Application.candidate_profile_id == candidate_profile_id,
                    Application.saved_job_id.in_(saved_job_ids),
                )
                .order_by(Application.created_at.desc())
            )
        )
        for application in applications_by_saved_job:
            if application.saved_job_id and application.saved_job_id not in lookup:
                lookup[application.saved_job_id] = application
    if not job_id_to_saved_job_id:
        return lookup
    applications_by_job = list(
        session.scalars(
            select(Application)
            .where(
                Application.candidate_profile_id == candidate_profile_id,
                Application.job_id.in_(job_id_to_saved_job_id),
            )
            .order_by(Application.created_at.desc())
        )
    )
    for application in applications_by_job:
        saved_job_id = job_id_to_saved_job_id.get(application.job_id)
        if saved_job_id and saved_job_id not in lookup:
            lookup[saved_job_id] = application
    return lookup


def get_application_for_saved_job(session: Session, saved_job: CandidateSavedJob, candidate_profile_id: str) -> Application | None:
    application = session.scalar(
        select(Application)
        .where(
            Application.candidate_profile_id == candidate_profile_id,
            Application.saved_job_id == saved_job.id,
        )
        .order_by(Application.created_at.desc())
        .limit(1)
    )
    if application is not None:
        return application
    if not saved_job.job_id:
        return None
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


def serialize_saved_job(
    link: CandidateSavedJob,
    *,
    application: Application | None = None,
    highlighted_job_search_run_id: str | None = None,
) -> dict[str, Any]:
    if link.job is not None:
        return serialize_legacy_saved_job(
            link,
            application=application,
            highlighted_job_search_run_id=highlighted_job_search_run_id,
        )
    if link.job_listing is None:
        raise ValueError(f"Saved job {link.id} is missing both job_id and job_listing_id.")
    job = link.job_listing
    job_url = job_listing_primary_url(job)
    highlighted = bool(highlighted_job_search_run_id and link.job_search_run_id == highlighted_job_search_run_id)
    application_requirements = compact_application_requirements_summary(job)
    return {
        "id": link.id,
        "candidate_profile_id": link.candidate_profile_id,
        "job_id": None,
        "job_listing_id": job.id,
        "jobSearchRunId": link.job_search_run_id,
        "highlighted": highlighted,
        "justAdded": highlighted,
        "latestDiscoveryRunId": highlighted_job_search_run_id,
        "title": job.title,
        "company_name": job.company_name,
        "job_url": job_url,
        "canonical_url": job.canonical_url,
        "apply_url": job.apply_url,
        "source": "job_sync",
        "source_provider": first_job_listing_source_provider(job),
        **application_requirements,
        "provider_type": "job_sync",
        "source_result_id": None,
        "source_query": None,
        "source_url": job.source_url,
        "source_updated_at": job.source_updated_at.isoformat() if job.source_updated_at else None,
        "company_website_url": None,
        "company_careers_url": None,
        "ats_provider": None,
        "ats_board_token": None,
        "provenance": "job_sync",
        "url_verification_status": "provider_unverified",
        "url_verification_checked_at": None,
        "url_verification_summary": "Synced provider inventory; URL was not verified during candidate discovery.",
        "location": job.location_display,
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


def serialize_legacy_saved_job(
    link: CandidateSavedJob,
    *,
    application: Application | None = None,
    highlighted_job_search_run_id: str | None = None,
) -> dict[str, Any]:
    job = link.job
    if job is None:
        raise ValueError(f"Saved job {link.id} is missing job_id.")
    highlighted = bool(highlighted_job_search_run_id and link.job_search_run_id == highlighted_job_search_run_id)
    return {
        "id": link.id,
        "candidate_profile_id": link.candidate_profile_id,
        "job_id": link.job_id,
        "job_listing_id": link.job_listing_id,
        "jobSearchRunId": link.job_search_run_id,
        "highlighted": highlighted,
        "justAdded": highlighted,
        "latestDiscoveryRunId": highlighted_job_search_run_id,
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


def job_listing_primary_url(job: Any) -> str:
    return job.apply_url or job.canonical_url or job.source_url or f"job_listing:{job.id}"


def first_job_listing_source_provider(job: Any) -> str | None:
    sources = getattr(job, "sources", None) or []
    for source in sources:
        if source.source_provider:
            return source.source_provider
    return None


def compact_application_requirements_summary(job: Any) -> dict[str, Any]:
    requirements = richest_application_requirements(job)
    fields = richest_application_fields(job)
    short_answers = requirements.get("shortAnswerQuestions") if isinstance(requirements, dict) else []
    return {
        "hasApplicationFields": bool(fields or requirements),
        "requiredFieldCount": fields.get("requiredFieldCount") if isinstance(fields, dict) else 0,
        "shortAnswerQuestionCount": len(short_answers) if isinstance(short_answers, list) else 0,
        "requiresResume": requirements.get("requiresResume") if isinstance(requirements, dict) else None,
        "requiresCoverLetter": requirements.get("requiresCoverLetter") if isinstance(requirements, dict) else None,
        "requiresPortfolioUrl": requirements.get("requiresPortfolioUrl") if isinstance(requirements, dict) else None,
        "requiresLinkedIn": requirements.get("requiresLinkedIn") if isinstance(requirements, dict) else None,
        "requiresWebsite": requirements.get("requiresWebsite") if isinstance(requirements, dict) else None,
    }


def richest_application_requirements(job: Any) -> dict[str, Any] | None:
    sources = getattr(job, "sources", None) or []
    candidates = [source.application_requirements_json for source in sources if source.application_requirements_json]
    if not candidates:
        return None
    return max(candidates, key=lambda item: len(item.get("shortAnswerQuestions") or []) + len(item.get("detectedMaterials") or []))


def richest_application_fields(job: Any) -> dict[str, Any] | None:
    sources = getattr(job, "sources", None) or []
    candidates = [source.application_fields_json for source in sources if source.application_fields_json]
    if not candidates:
        return None
    return max(candidates, key=lambda item: int(item.get("rawFieldCount") or 0))


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
