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
    return {
        "jobSync": {
            "runs": sync_runs,
            "runCount": len(sync_runs),
            "rawResultCount": sum(int(row.get("raw") or 0) for row in sync_runs),
            "normalizedCount": sum(int(row.get("normalized") or 0) for row in sync_runs),
            "createdCount": sum(int(row.get("created") or 0) for row in sync_runs),
            "updatedCount": sum(int(row.get("updated") or 0) for row in sync_runs),
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
        },
    }


def format_candidate_discovery_diagnostics(diagnostics: dict[str, Any]) -> str:
    lines = ["Job Sync"]
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
    lines.append(f"- Added to candidate jobs list: {review.get('addedToCandidateJobsList', 0)}")
    lines.append(f"- Recorded model rejections: {review.get('recordedModelRejections', 0)}")
    return "\n".join(lines)
