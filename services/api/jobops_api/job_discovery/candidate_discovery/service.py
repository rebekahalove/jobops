from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.models import CandidateProfile, JobListing, JobListingSource, JobSearchRun
from ...model_connector import ModelConnector
from ...settings import Settings
from ..job_sync.adzuna_service import sync_adzuna_signatures, upsert_adzuna_sync_signature
from ..job_sync.greenhouse_service import sync_greenhouse_boards
from ..models import JobDiscoveryRequest
from .diagnostics import build_candidate_discovery_diagnostics
from .models import CandidateDiscoveryResult, DbJobSearchPlan, JobPoolEntry
from .planner import DbJobSearchPlanner
from .query_builder import JobListingQueryBuilder, job_listing_to_pool_entry
from .repositories import CandidateJobRepository, rejection_reason_counts
from .reviewer import JobReviewSelector, validate_review_result


class CandidateJobDiscoveryService:
    def __init__(
        self,
        *,
        session: Session,
        settings: Settings,
        connector: ModelConnector | None = None,
        planner: DbJobSearchPlanner | None = None,
        reviewer: JobReviewSelector | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.connector = connector
        self.planner = planner or DbJobSearchPlanner()
        self.reviewer = reviewer or JobReviewSelector()

    def run(
        self,
        request: JobDiscoveryRequest,
        *,
        candidate_profile: CandidateProfile,
        current_saved_jobs: list[dict[str, Any]],
        current_saved_companies: list[dict[str, Any]],
        target_context: dict[str, Any],
        private_profile_context: dict[str, Any],
        job_search_run_id: str | None = None,
    ) -> CandidateDiscoveryResult:
        run = self.get_or_create_run(
            candidate_profile_id=candidate_profile.id,
            command_text=request.latest_user_message,
            job_search_run_id=job_search_run_id,
        )
        plan = self.planner.plan(
            request,
            connector=self.connector,
            settings=self.settings,
            current_saved_jobs=current_saved_jobs,
            current_saved_companies=current_saved_companies,
            target_context=target_context,
            private_profile_context=private_profile_context,
        )
        run.search_plan_json = serialize_plan(plan)
        run.search_mode = "db_backed"
        run.provider_names = ["job_sync", "database", "model_review"]
        run.status = "running"
        run.started_at = run.started_at or datetime.now(UTC)

        job_sync_results = list(self.ensure_inventory(candidate_profile_id=candidate_profile.id, plan=plan))
        query_builder = JobListingQueryBuilder(self.session)
        job_listings, query_counts = query_builder.execute_plan(candidate_profile.id, plan)
        pool_entries = self.build_pool_entries(job_listings)[: plan.max_jobs_for_model_review]
        review = self.reviewer.review(
            request,
            connector=self.connector,
            settings=self.settings,
            job_pool=pool_entries,
            max_selected=self.settings.job_discovery_save_limit,
        )
        review = validate_review_result(review, tuple(entry.job_listing_id for entry in pool_entries))
        model_review_completed = bool(review.diagnostics.get("modelReviewCompleted", True))
        repository = CandidateJobRepository(self.session)
        selected_links, updated_links, rejected_links = repository.apply_review_result(
            candidate_profile_id=candidate_profile.id,
            job_search_run_id=run.id,
            review=review,
        )
        reason_counts = rejection_reason_counts(rejected_links)
        diagnostics = build_candidate_discovery_diagnostics(
            job_sync_results=tuple(job_sync_results),
            query_counts=query_counts,
            unique_job_pool_count=len(job_listings),
            jobs_reviewed_count=len(pool_entries) if model_review_completed else 0,
            added_count=len(selected_links),
            rejected_count=len(rejected_links),
            rejection_reason_counts=reason_counts,
            review_diagnostics=review.diagnostics,
        )
        diagnostics["addedJobIds"] = [link.id for link in selected_links]
        diagnostics["addedJobListingIds"] = [link.job_listing_id for link in selected_links if link.job_listing_id]
        run.status = "completed"
        run.completed_at = datetime.now(UTC)
        run.total_provider_results = sum(getattr(result, "raw_result_count", 0) for result in job_sync_results)
        run.candidate_pool_count = len(job_listings)
        run.candidate_count_after_dedupe = len(job_listings)
        run.model_selected_count = len(selected_links)
        run.saved_count = len(selected_links)
        run.updated_existing_count = len(updated_links)
        run.duplicate_count = 0
        run.skipped_count = len(rejected_links)
        run.provider_error_count = sum(1 for result in job_sync_results if getattr(result, "status", "") == "failed")
        run.run_diagnostics_json = diagnostics
        self.session.flush()
        return CandidateDiscoveryResult(
            assistant_message=review.user_visible_summary,
            job_search_run_id=run.id,
            search_plan=plan,
            selected_candidate_jobs=tuple(selected_links),
            updated_candidate_jobs=tuple(updated_links),
            rejected_candidate_jobs=tuple(rejected_links),
            job_sync_results=tuple(job_sync_results),
            query_counts=query_counts,
            unique_job_pool_count=len(job_listings),
            jobs_reviewed_count=len(pool_entries) if model_review_completed else 0,
            added_count=len(selected_links),
            updated_count=len(updated_links),
            rejected_count=len(rejected_links),
            diagnostics=diagnostics,
        )

    def ensure_inventory(self, *, candidate_profile_id: str, plan: DbJobSearchPlan) -> tuple[Any, ...]:
        results: list[Any] = []
        results.extend(
            sync_greenhouse_boards(
                self.session,
                settings=self.settings,
                candidate_profile_id=candidate_profile_id,
                include_configured=False,
                force=False,
                freshness_hours=24,
            )
        )
        results.extend(
            sync_adzuna_signatures(
                self.session,
                settings=self.settings,
                enabled_only=True,
                force=False,
            )
        )
        for raw_signature in plan.proposed_adzuna_signatures:
            query_text = str(raw_signature.get("queryText") or raw_signature.get("query_text") or "").strip()
            display_location = raw_signature.get("displayLocation") or raw_signature.get("display_location")
            if not query_text:
                continue
            signature = upsert_adzuna_sync_signature(
                self.session,
                query_text=query_text,
                display_location=str(display_location) if display_location else None,
                provider_country=raw_signature.get("providerCountry") or raw_signature.get("provider_country"),
                query_kind=str(raw_signature.get("queryKind") or "model_planned"),
                source="model_planner",
                max_pages=int(raw_signature.get("maxPages") or 1),
            )
            results.extend(
                sync_adzuna_signatures(
                    self.session,
                    settings=self.settings,
                    signature_ids=[signature.id],
                    enabled_only=False,
                    force=False,
                )
            )
        return tuple(results)

    def build_pool_entries(self, jobs: list[JobListing]) -> list[JobPoolEntry]:
        providers_by_job_id: dict[str, tuple[str, ...]] = {}
        if jobs:
            sources = self.session.scalars(
                select(JobListingSource).where(JobListingSource.job_listing_id.in_([job.id for job in jobs]))
            ).all()
            grouped: dict[str, list[str]] = {}
            for source in sources:
                grouped.setdefault(source.job_listing_id, [])
                if source.source_provider not in grouped[source.job_listing_id]:
                    grouped[source.job_listing_id].append(source.source_provider)
            providers_by_job_id = {job_id: tuple(providers) for job_id, providers in grouped.items()}
        return [job_listing_to_pool_entry(job, source_providers=providers_by_job_id.get(job.id, ())) for job in jobs]

    def get_or_create_run(self, *, candidate_profile_id: str, command_text: str, job_search_run_id: str | None) -> JobSearchRun:
        if job_search_run_id:
            existing = self.session.get(JobSearchRun, job_search_run_id)
            if existing is not None and existing.candidate_profile_id == candidate_profile_id:
                return existing
        run = JobSearchRun(
            candidate_profile_id=candidate_profile_id,
            command_text=command_text,
            search_plan_json={},
            run_diagnostics_json={},
            provider_names=[],
            search_mode="db_backed",
            status="started",
            started_at=datetime.now(UTC),
        )
        self.session.add(run)
        self.session.flush()
        return run


def serialize_plan(plan: DbJobSearchPlan) -> dict[str, Any]:
    return {
        "jobScope": plan.job_scope,
        "queries": [json_safe(asdict(query)) for query in plan.queries],
        "replanRules": {
            "minJobPoolSize": plan.min_job_pool_size,
            "maxJobPoolSize": plan.max_job_pool_size,
            "maxJobsForModelReview": plan.max_jobs_for_model_review,
        },
        "proposedAdzunaSignatures": list(plan.proposed_adzuna_signatures),
    }


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
