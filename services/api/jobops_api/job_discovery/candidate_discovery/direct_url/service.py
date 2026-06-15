from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import selectinload

from ....db.models import CandidateProfile, CandidateSavedJob, JobListing, JobSearchRun
from ....settings import Settings
from ...models import JobDiscoveryRequest
from ..diagnostics import build_candidate_discovery_diagnostics
from ..models import CandidateDiscoveryResult, DbJobSearchPlan
from .models import DirectJobUrlIngestionContext, DirectJobUrlIngestionResult, DirectJobUrlProvider
from .providers.greenhouse import GreenhouseDirectJobUrlProvider
from .repository import DirectUrlSavedJobRepository


HTTP_URL_PATTERN = re.compile(r"https?://[^\s<>()\"']+")


class DirectJobUrlDiscoveryService:
    def __init__(
        self,
        *,
        session,
        settings: Settings,
        providers: tuple[DirectJobUrlProvider, ...] | None = None,
        saved_job_repository: DirectUrlSavedJobRepository | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.providers = providers or (GreenhouseDirectJobUrlProvider(),)
        self.saved_job_repository = saved_job_repository or DirectUrlSavedJobRepository(session)

    def run(
        self,
        request: JobDiscoveryRequest,
        *,
        candidate_profile: CandidateProfile,
        current_saved_companies: list[dict[str, Any]],
        plan: DbJobSearchPlan,
        run: JobSearchRun,
    ) -> CandidateDiscoveryResult:
        urls = extract_http_urls(request.latest_user_message)
        planner_diagnostics = {
            "status": "planned",
            "modelUsed": True,
            "planningFailed": False,
            "mode": plan.mode,
            "modeRationale": plan.mode_rationale,
            "jobScope": plan.job_scope,
            "reviewTask": plan.review_plan.task,
            "plannerAttemptCount": plan.planner_attempt_count,
            "criticAttemptCount": plan.critic_attempt_count,
            "rejectedPlans": list(plan.rejected_plans),
            "finalPlanStatus": plan.final_plan_status,
            "directUrlCount": len(urls),
        }
        if not urls:
            return self.complete_without_ingestion(
                run,
                plan=plan,
                planner_diagnostics=planner_diagnostics,
                assistant_message="I could not add a job because I could not find a URL in your message.",
                no_jobs_added_reason="direct_url_missing_url",
                direct_url_results=[],
                status="failed",
                error="direct_url_missing_url",
            )

        context = DirectJobUrlIngestionContext(
            session=self.session,
            settings=self.settings,
            candidate_profile=candidate_profile,
            current_saved_companies=current_saved_companies,
            latest_user_message=request.latest_user_message,
            job_search_run_id=run.id,
        )
        ingestion_results: list[DirectJobUrlIngestionResult] = []
        selected_links: list[CandidateSavedJob] = []
        updated_links: list[CandidateSavedJob] = []

        for url in urls:
            provider = next((item for item in self.providers if item.can_handle(url)), None)
            if provider is None:
                ingestion_results.append(
                    DirectJobUrlIngestionResult(
                        status="unsupported",
                        provider="unsupported",
                        url=url,
                        diagnostics={"directUrl": url, "unsupportedReason": "unsupported_url"},
                        error="unsupported_url",
                    )
                )
                continue

            result = provider.ingest(url, context)
            if result.job_listing_id:
                saved = self.saved_job_repository.save_or_refresh(
                    candidate_profile_id=candidate_profile.id,
                    job_listing_id=result.job_listing_id,
                    job_search_run_id=run.id,
                    source_command=request.latest_user_message,
                    diagnostics=result.diagnostics,
                )
                result = replace(
                    result,
                    status="added" if saved.created else "refreshed",
                    saved_job_id=saved.saved_job.id,
                    created_saved_job=saved.created,
                    refreshed_saved_job=saved.refreshed,
                    saved_job=saved.saved_job,
                    diagnostics={
                        **result.diagnostics,
                        "savedJobId": saved.saved_job.id,
                        "createdSavedJob": saved.created,
                        "refreshedSavedJob": saved.refreshed,
                    },
                )
                if saved.created:
                    selected_links.append(saved.saved_job)
                else:
                    updated_links.append(saved.saved_job)
            ingestion_results.append(result)

        sync_results = tuple(result.sync_result for result in ingestion_results if result.sync_result is not None)
        successful_count = sum(1 for result in ingestion_results if result.job_listing_id)
        added_count = len(selected_links)
        updated_count = len(updated_links)
        failed_count = sum(1 for result in ingestion_results if result.status == "failed")
        unsupported_count = sum(1 for result in ingestion_results if result.status == "unsupported")
        diagnostics = build_candidate_discovery_diagnostics(
            job_sync_results=sync_results,
            query_counts=(),
            unique_job_pool_count=successful_count,
            jobs_reviewed_count=0,
            added_count=added_count,
            rejected_count=0,
            rejection_reason_counts={},
            review_diagnostics={
                "modelReviewCompleted": False,
                "modelReviewSkippedReason": "direct_job_url",
                "selectedJobsLabel": "Added to jobs list",
            },
            planner_diagnostics=planner_diagnostics,
        )
        diagnostics["directUrlIngestion"] = {
            "urls": urls,
            "results": [serialize_direct_url_result(result) for result in ingestion_results],
            "successfulCount": successful_count,
            "addedCount": added_count,
            "updatedCount": updated_count,
            "failedCount": failed_count,
            "unsupportedCount": unsupported_count,
        }
        diagnostics["addedJobIds"] = [link.id for link in selected_links]
        diagnostics["addedJobListingIds"] = [link.job_listing_id for link in selected_links if link.job_listing_id]
        diagnostics["updatedJobIds"] = [link.id for link in updated_links]
        diagnostics["updatedJobListingIds"] = [link.job_listing_id for link in updated_links if link.job_listing_id]
        if successful_count == 0:
            diagnostics["noJobsAddedReason"] = "direct_url_ingestion_failed" if failed_count else "unsupported_direct_job_url"

        run.search_mode = "db_backed"
        run.provider_names = ["direct_job_url", *sorted({result.provider for result in ingestion_results})]
        run.status = "completed" if successful_count else "failed"
        run.completed_at = datetime.now(UTC)
        run.total_provider_results = sum(result.raw_result_count for result in sync_results)
        run.candidate_pool_count = successful_count
        run.candidate_count_after_dedupe = successful_count
        run.model_selected_count = added_count
        run.saved_count = added_count
        run.updated_existing_count = updated_count
        run.duplicate_count = 0
        run.skipped_count = failed_count + unsupported_count
        run.provider_error_count = failed_count
        run.error = None if successful_count else diagnostics.get("noJobsAddedReason")
        run.run_diagnostics_json = diagnostics
        self.session.flush()

        return CandidateDiscoveryResult(
            assistant_message=assistant_message_for_results(ingestion_results),
            job_search_run_id=run.id,
            search_plan=plan,
            selected_candidate_jobs=tuple(selected_links),
            updated_candidate_jobs=tuple(updated_links),
            rejected_candidate_jobs=(),
            job_sync_results=sync_results,
            query_counts=(),
            unique_job_pool_count=successful_count,
            jobs_reviewed_count=0,
            added_count=added_count,
            updated_count=updated_count,
            rejected_count=0,
            diagnostics=diagnostics,
        )

    def complete_without_ingestion(
        self,
        run: JobSearchRun,
        *,
        plan: DbJobSearchPlan,
        planner_diagnostics: dict[str, Any],
        assistant_message: str,
        no_jobs_added_reason: str,
        direct_url_results: list[dict[str, Any]],
        status: str,
        error: str | None,
    ) -> CandidateDiscoveryResult:
        diagnostics = build_candidate_discovery_diagnostics(
            job_sync_results=(),
            query_counts=(),
            unique_job_pool_count=0,
            jobs_reviewed_count=0,
            added_count=0,
            rejected_count=0,
            rejection_reason_counts={},
            review_diagnostics={"modelReviewCompleted": False, "modelReviewSkippedReason": "direct_job_url"},
            planner_diagnostics=planner_diagnostics,
        )
        diagnostics["directUrlIngestion"] = {"urls": [], "results": direct_url_results, "successfulCount": 0}
        diagnostics["noJobsAddedReason"] = no_jobs_added_reason
        diagnostics["addedJobIds"] = []
        diagnostics["addedJobListingIds"] = []
        run.search_mode = "db_backed"
        run.provider_names = ["direct_job_url"]
        run.status = status
        run.completed_at = datetime.now(UTC)
        run.error = error
        run.run_diagnostics_json = diagnostics
        self.session.flush()
        return CandidateDiscoveryResult(
            assistant_message=assistant_message,
            job_search_run_id=run.id,
            search_plan=plan,
            selected_candidate_jobs=(),
            updated_candidate_jobs=(),
            rejected_candidate_jobs=(),
            job_sync_results=(),
            query_counts=(),
            unique_job_pool_count=0,
            jobs_reviewed_count=0,
            added_count=0,
            updated_count=0,
            rejected_count=0,
            diagnostics=diagnostics,
        )


def extract_http_urls(text: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for match in HTTP_URL_PATTERN.finditer(text or ""):
        url = match.group(0).rstrip(".,;:!?)\"]}'")
        key = url.casefold()
        if url and key not in seen:
            urls.append(url)
            seen.add(key)
    return urls


def serialize_direct_url_result(result: DirectJobUrlIngestionResult) -> dict[str, Any]:
    return {
        "status": result.status,
        "provider": result.provider,
        "directUrl": result.url,
        "jobListingId": result.job_listing_id,
        "jobListingSourceId": result.job_listing_source_id,
        "savedJobId": result.saved_job_id,
        "companyId": result.company_id,
        "candidateCompanyId": result.candidate_company_id,
        "createdListing": result.created_listing,
        "updatedListing": result.updated_listing,
        "createdSavedJob": result.created_saved_job,
        "refreshedSavedJob": result.refreshed_saved_job,
        "error": result.error,
        "diagnostics": result.diagnostics,
    }


def assistant_message_for_results(results: list[DirectJobUrlIngestionResult]) -> str:
    added = sum(1 for result in results if result.created_saved_job)
    refreshed = sum(1 for result in results if result.refreshed_saved_job)
    unsupported = [result for result in results if result.status == "unsupported"]
    failed = [result for result in results if result.status == "failed"]
    if added == 1 and not refreshed and not failed and not unsupported:
        return "Added 1 job from the Greenhouse URL to your jobs list."
    if refreshed == 1 and not added and not failed and not unsupported:
        return "That Greenhouse job was already on your jobs list, so I refreshed it."
    if added or refreshed:
        return f"Added {added} job(s) and refreshed {refreshed} existing job(s) from the direct URL request."
    if unsupported:
        return "I could not add that URL because it is not a supported job URL yet."
    if failed and any(result.error == "not_found" for result in failed):
        return "I could not find that Greenhouse job on the public board."
    return "I could not add that direct job URL."
