from __future__ import annotations

from typing import Any


def build_candidate_discovery_diagnostics(
    *,
    job_sync_results: tuple[Any, ...],
    query_counts: tuple[tuple[str, int], ...],
    unique_job_pool_count: int,
    jobs_reviewed_count: int,
    added_count: int,
    rejected_count: int,
    rejection_reason_counts: dict[str, int],
    review_diagnostics: dict[str, Any] | None = None,
    planner_diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sync_runs = [
        {
            "syncKey": getattr(result.request, "sync_key", None),
            "status": result.status,
            "raw": result.raw_result_count,
            "normalized": result.normalized_count,
            "created": result.created_count,
            "updated": result.updated_count,
        }
        for result in job_sync_results
    ]
    query_rows = [{"label": label, "jobCount": count} for label, count in query_counts]
    review_diagnostics = review_diagnostics or {}
    no_jobs_added_reason = infer_no_jobs_added_reason(
        unique_job_pool_count=unique_job_pool_count,
        jobs_reviewed_count=jobs_reviewed_count,
        added_count=added_count,
        model_review_completed=review_diagnostics.get("modelReviewCompleted", True),
        model_review_fallback=bool(review_diagnostics.get("modelReviewFallback")),
        review_validation=review_diagnostics.get("reviewValidation"),
    )
    diagnostics = {
        "planner": planner_diagnostics or {"status": "planned", "modelUsed": True, "planningFailed": False},
        "jobSync": {
            "runs": sync_runs,
            "runCount": len(sync_runs),
            "rawResultCount": sum(int(row.get("raw") or 0) for row in sync_runs),
            "normalizedCount": sum(int(row.get("normalized") or 0) for row in sync_runs),
            "createdCount": sum(int(row.get("created") or 0) for row in sync_runs),
            "updatedCount": sum(int(row.get("updated") or 0) for row in sync_runs),
            "completedCount": sum(1 for row in sync_runs if row.get("status") == "completed"),
            "failedCount": sum(1 for row in sync_runs if row.get("status") == "failed"),
        },
        "databaseQueries": {
            "queries": query_rows,
            "uniqueJobPoolCount": unique_job_pool_count,
            "totalRowsMatched": sum(count for _, count in query_counts),
        },
        "modelReview": {
            "uniqueJobsInPool": unique_job_pool_count,
            "jobsReviewedByModel": jobs_reviewed_count,
            "addedToCandidateJobsList": added_count,
            "recordedModelRejections": rejected_count,
            "topRejectionReasonCounts": rejection_reason_counts,
            "rejectionReasonCounts": rejection_reason_counts,
            **review_diagnostics,
        },
        "noJobsAddedReason": no_jobs_added_reason,
    }
    return diagnostics


def format_candidate_discovery_diagnostics(diagnostics: dict[str, Any]) -> str:
    lines = ["Planner"]
    planner = diagnostics.get("planner", {}) if isinstance(diagnostics.get("planner"), dict) else {}
    if planner.get("mode"):
        mode_line = f"- Mode: {planner.get('mode')}"
        if planner.get("modeRationale"):
            mode_line = f"{mode_line} - {planner.get('modeRationale')}"
        lines.append(mode_line)
    if planner.get("plannerAttemptCount") or planner.get("criticAttemptCount"):
        lines.append(
            f"- Planner attempts: {planner.get('plannerAttemptCount', 0)}; "
            f"critic attempts: {planner.get('criticAttemptCount', 0)}; "
            f"final status: {planner.get('finalPlanStatus') or planner.get('status') or 'unknown'}"
        )
    for item in planner.get("rejectedPlans", []) if isinstance(planner.get("rejectedPlans"), list) else []:
        if isinstance(item, dict):
            lines.append(f"- Rejected plan: {item.get('issueCode') or 'unknown'} - {item.get('issueMessage') or '-'}")
    for item in planner.get("plannedSyncSignatures", []) if isinstance(planner.get("plannedSyncSignatures"), list) else []:
        if not isinstance(item, dict):
            continue
        lines.append(
            f"- Sync token {item.get('syncKey') or '-'} - {item.get('action') or 'planned'} - "
            f"query={item.get('queryText') or '-'} location={item.get('displayLocation') or '-'} "
            f"country={item.get('providerCountry') or '-'} where={item.get('providerWhere') or '-'} "
            f"pages={item.get('maxPages') or '-'}"
        )
    for item in planner.get("existingSyncSignaturesSelected", []) if isinstance(planner.get("existingSyncSignaturesSelected"), list) else []:
        if not isinstance(item, dict):
            continue
        lines.append(
            f"- Sync token {item.get('syncKey') or '-'} - {item.get('action') or 'reused'} - "
            f"query={item.get('queryText') or '-'} location={item.get('displayLocation') or '-'} "
            f"country={item.get('providerCountry') or '-'} where={item.get('providerWhere') or '-'} "
            f"pages={item.get('maxPages') or '-'}"
        )
    for item in planner.get("plannedDbQueries", []) if isinstance(planner.get("plannedDbQueries"), list) else []:
        if not isinstance(item, dict):
            continue
        lines.append(
            f"- DB search \"{item.get('label') or 'Synced job inventory search'}\" - "
            f"title any: {', '.join(item.get('titleTermsAny') or []) or '-'} - "
            f"description any: {', '.join(item.get('descriptionTermsAny') or []) or '-'} - "
            f"country: {', '.join(item.get('locationCountriesAny') or []) or '-'} - "
            f"work mode: {', '.join(item.get('remoteWorkModesAny') or []) or '-'}"
        )
    if planner.get("planningFailed"):
        lines.append(f"- Planning failed: {planner.get('error') or 'unknown'}")
    lines.append("")
    lines.append("Job Sync")
    job_sync = diagnostics.get("jobSync", {})
    job_sync_rows = job_sync.get("runs", []) if isinstance(job_sync, dict) else job_sync
    for item in job_sync_rows:
        lines.append(
            f"- {item.get('syncKey') or '-'} - {item.get('status')} "
            f"raw={item.get('raw', 0)} normalized={item.get('normalized', 0)} "
            f"created={item.get('created', 0)} updated={item.get('updated', 0)}"
        )
    lines.append("")
    lines.append("Database queries")
    database_queries = diagnostics.get("databaseQueries", {})
    query_rows = database_queries.get("queries", []) if isinstance(database_queries, dict) else database_queries
    for item in query_rows:
        lines.append(f"- {item.get('label')} - {item.get('jobCount', 0)} jobs")
    lines.append("")
    review = diagnostics.get("modelReview", {})
    lines.append("Model review")
    lines.append(f"- Unique jobs in pool: {review.get('uniqueJobsInPool', 0)}")
    lines.append(f"- Jobs reviewed by model: {review.get('jobsReviewedByModel', 0)}")
    selected_label = review.get("selectedJobsLabel") or "Added to jobs list"
    lines.append(f"- {selected_label}: {review.get('addedToCandidateJobsList', 0)}")
    lines.append(f"- Recorded model rejections: {review.get('recordedModelRejections', 0)}")
    if review.get("modelReviewFallback"):
        lines.append(f"- Model review fallback: {review.get('modelReviewFailureReason') or 'unknown'}")
    if diagnostics.get("noJobsAddedReason"):
        lines.append(f"- No jobs added reason: {diagnostics.get('noJobsAddedReason')}")
    return "\n".join(lines)


def infer_no_jobs_added_reason(
    *,
    unique_job_pool_count: int,
    jobs_reviewed_count: int,
    added_count: int,
    model_review_completed: object,
    model_review_fallback: bool,
    review_validation: object,
) -> str | None:
    if added_count > 0:
        return None
    if isinstance(review_validation, dict) and review_validation.get("planningFailed"):
        return "model_planning_failed"
    if unique_job_pool_count <= 0:
        return "no_db_matches"
    if model_review_completed is False or model_review_fallback:
        return "model_review_failed"
    if isinstance(review_validation, dict) and review_validation.get("invalidSelectedJobIds"):
        return "review_validation_removed_all_selected_ids"
    if jobs_reviewed_count > 0:
        return "model_selected_zero"
    return "unknown"
