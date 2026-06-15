from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ...db.models import CandidateProfile, CandidateSavedJob, JobListing, JobListingSource, JobSearchQueryRun, JobSearchRun, JobSyncRun, JobSyncSignature
from ...model_connector import ModelConnector
from ...settings import Settings
from ..job_sync.adzuna_service import sync_adzuna_signatures, upsert_adzuna_sync_signature
from ..job_sync.greenhouse_service import sync_greenhouse_boards
from ..models import JobDiscoveryRequest
from .diagnostics import build_candidate_discovery_diagnostics
from .direct_url import DirectJobUrlDiscoveryService
from .models import CandidateDiscoveryResult, DbJobSearchPlan, DbJobSearchQuery, JobPoolEntry
from .planner import CandidateDiscoveryPlanCritic, DbJobSearchPlanner, DbJobSearchPlanningError
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
        critic: CandidateDiscoveryPlanCritic | None = None,
        reviewer: JobReviewSelector | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.connector = connector
        self._uses_default_planner = planner is None
        self.planner = planner or DbJobSearchPlanner()
        self.critic = critic or CandidateDiscoveryPlanCritic()
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
        self.mark_planning_started(run)
        inventory_context = self.build_planner_inventory_context(current_saved_jobs=current_saved_jobs)
        try:
            plan = self.plan_with_model_critique(
                request,
                current_saved_jobs=current_saved_jobs,
                current_saved_companies=current_saved_companies,
                target_context=target_context,
                private_profile_context=private_profile_context,
                inventory_context=inventory_context,
            )
        except DbJobSearchPlanningError as exc:
            return self.complete_planning_failure_run(run, exc)
        plan, planning_corrections = self.apply_jobs_list_ranking_safety(plan)
        run.search_plan_json = serialize_plan(plan)
        run.search_mode = "db_backed"
        if plan.mode == "direct_job_url":
            return DirectJobUrlDiscoveryService(session=self.session, settings=self.settings).run(
                request,
                candidate_profile=candidate_profile,
                current_saved_companies=current_saved_companies,
                plan=plan,
                run=run,
            )
        run.provider_names = ["job_sync", "database", "model_review"]
        run.status = "running"
        run.started_at = run.started_at or datetime.now(UTC)

        job_sync_results = list(self.ensure_inventory(candidate_profile_id=candidate_profile.id, plan=plan))
        query_builder = JobListingQueryBuilder(self.session)
        job_listings, query_counts = query_builder.execute_plan(candidate_profile.id, plan)
        self.persist_db_query_runs(run.id, plan.queries, query_counts, deduped_count=len(job_listings))
        if self.should_replan_for_pool_size(plan, len(job_listings)):
            try:
                replan_reason = "too_few_jobs" if len(job_listings) < plan.min_job_pool_size else "too_many_jobs"
                plan = self.replan_from_execution(
                    request,
                    plan=plan,
                    current_saved_jobs=current_saved_jobs,
                    current_saved_companies=current_saved_companies,
                    target_context=target_context,
                    private_profile_context=private_profile_context,
                    inventory_context=inventory_context,
                    execution_facts={
                        "reason": replan_reason,
                        "jobPoolSize": len(job_listings),
                        "queryCounts": [{"label": label, "jobCount": count} for label, count in query_counts],
                        "minJobPoolSize": plan.min_job_pool_size,
                        "maxJobPoolSize": plan.max_job_pool_size,
                    },
                )
                job_sync_results.extend(self.ensure_inventory(candidate_profile_id=candidate_profile.id, plan=plan))
                job_listings, query_counts = query_builder.execute_plan(candidate_profile.id, plan)
                self.persist_db_query_runs(run.id, plan.queries, query_counts, deduped_count=len(job_listings))
            except DbJobSearchPlanningError as exc:
                return self.complete_planning_failure_run(run, exc)
        planner_diagnostics = self.build_planner_diagnostics(plan, job_sync_results)
        if planning_corrections:
            planner_diagnostics["inputCapCorrections"] = planning_corrections
        pool_entries = self.build_pool_entries(job_listings, candidate_profile_id=candidate_profile.id)
        if not is_jobs_list_ranking_plan(plan):
            pool_entries = pool_entries[: plan.max_jobs_for_model_review]
        review = self.reviewer.review(
            request,
            connector=self.connector,
            settings=self.settings,
            job_pool=pool_entries,
            max_selected=self.settings.job_discovery_save_limit,
            review_mode=plan.review_plan.task,
            requested_count=plan.review_plan.requested_count,
            allow_rejections=plan.review_plan.allow_rejections,
        )
        review = validate_review_result(review, tuple(entry.job_listing_id for entry in pool_entries))
        model_review_completed = bool(review.diagnostics.get("modelReviewCompleted", True))
        repository = CandidateJobRepository(self.session)
        if is_jobs_list_ranking_plan(plan):
            selected_job_listing_ids = [decision.job_listing_id for decision in review.selected_jobs]
            selected_links = self.load_existing_saved_links_for_recommendations(
                candidate_profile.id,
                selected_job_listing_ids,
            )
            found_recommended_listing_ids = {link.job_listing_id for link in selected_links if link.job_listing_id}
            ignored_non_list_recommendations = [
                job_listing_id for job_listing_id in selected_job_listing_ids if job_listing_id not in found_recommended_listing_ids
            ]
            updated_links: list[CandidateSavedJob] = []
            rejected_links: list[CandidateSavedJob] = []
        else:
            ignored_non_list_recommendations = []
            selected_links, updated_links, rejected_links = repository.apply_review_result(
                candidate_profile_id=candidate_profile.id,
                job_search_run_id=run.id,
                review=review,
            )
        reason_counts = rejection_reason_counts(rejected_links)
        is_ranking = is_jobs_list_ranking_plan(plan)
        added_count = 0 if is_ranking else len(selected_links)
        recommended_existing_count = len(selected_links) if is_ranking else 0
        diagnostics = build_candidate_discovery_diagnostics(
            job_sync_results=tuple(job_sync_results),
            query_counts=query_counts,
            unique_job_pool_count=len(job_listings),
            jobs_reviewed_count=len(pool_entries) if model_review_completed else 0,
            added_count=added_count,
            rejected_count=len(rejected_links),
            rejection_reason_counts=reason_counts,
            review_diagnostics=review.diagnostics,
            planner_diagnostics=planner_diagnostics,
        )
        diagnostics["modelReview"]["selectedJobsLabel"] = selected_jobs_label_for_scope(plan.job_scope)
        assistant_message = review.user_visible_summary
        if is_ranking:
            diagnostics["modelReview"]["recommendedExistingJobCount"] = recommended_existing_count
            diagnostics["modelReview"]["requestedRecommendationCount"] = plan.review_plan.requested_count or self.settings.job_discovery_save_limit
            diagnostics["modelReview"]["eligibleJobsListCount"] = len(job_listings)
            validation = review.diagnostics.get("reviewValidation") if isinstance(review.diagnostics.get("reviewValidation"), dict) else {}
            invalid_selected_ids = [
                str(item) for item in validation.get("invalidSelectedJobIds", []) if str(item).strip()
            ]
            ignored_non_list_recommendations = list(dict.fromkeys([*ignored_non_list_recommendations, *invalid_selected_ids]))
            diagnostics["modelReview"]["ignoredNonListRecommendations"] = len(ignored_non_list_recommendations)
            diagnostics["modelReview"]["ignoredNonListRecommendationJobListingIds"] = ignored_non_list_recommendations
            if len(job_listings) < diagnostics["modelReview"]["requestedRecommendationCount"]:
                diagnostics["modelReview"]["fewerThanRequestedRecommendations"] = True
                diagnostics["modelReview"]["availableMatchingSavedListJobs"] = len(job_listings)
                if "search" not in assistant_message.casefold():
                    assistant_message = (
                        f"{assistant_message} Only {len(job_listings)} matching saved-list job(s) were available. "
                        "Would you like me to search for new jobs?"
                    )
            if recommended_existing_count:
                diagnostics["noJobsAddedReason"] = None
            diagnostics["addedJobIds"] = []
            diagnostics["addedJobListingIds"] = []
            diagnostics["recommendedJobIds"] = [link.id for link in selected_links]
            diagnostics["recommendedJobListingIds"] = [link.job_listing_id for link in selected_links if link.job_listing_id]
        else:
            diagnostics["addedJobIds"] = [link.id for link in selected_links]
            diagnostics["addedJobListingIds"] = [link.job_listing_id for link in selected_links if link.job_listing_id]
        run.status = "completed"
        run.completed_at = datetime.now(UTC)
        run.total_provider_results = sum(getattr(result, "raw_result_count", 0) for result in job_sync_results)
        run.candidate_pool_count = len(job_listings)
        run.candidate_count_after_dedupe = len(job_listings)
        run.model_selected_count = len(selected_links)
        run.saved_count = added_count
        run.updated_existing_count = len(updated_links)
        run.duplicate_count = 0
        run.skipped_count = len(rejected_links)
        run.provider_error_count = sum(1 for result in job_sync_results if getattr(result, "status", "") == "failed")
        run.run_diagnostics_json = diagnostics
        self.session.flush()
        return CandidateDiscoveryResult(
            assistant_message=assistant_message,
            job_search_run_id=run.id,
            search_plan=plan,
            selected_candidate_jobs=() if is_ranking else tuple(selected_links),
            updated_candidate_jobs=tuple(updated_links),
            rejected_candidate_jobs=tuple(rejected_links),
            recommended_candidate_jobs=tuple(selected_links) if is_ranking else (),
            job_sync_results=tuple(job_sync_results),
            query_counts=query_counts,
            unique_job_pool_count=len(job_listings),
            jobs_reviewed_count=len(pool_entries) if model_review_completed else 0,
            added_count=added_count,
            updated_count=len(updated_links),
            rejected_count=len(rejected_links),
            recommended_existing_count=recommended_existing_count,
            requested_recommendation_count=plan.review_plan.requested_count,
            eligible_jobs_list_count=len(job_listings) if is_ranking else None,
            diagnostics=diagnostics,
        )

    def plan_with_model_critique(
        self,
        request: JobDiscoveryRequest,
        *,
        current_saved_jobs: list[dict[str, Any]],
        current_saved_companies: list[dict[str, Any]],
        target_context: dict[str, Any],
        private_profile_context: dict[str, Any],
        inventory_context: dict[str, Any],
    ) -> DbJobSearchPlan:
        planner_attempt_count = 1
        critic_attempt_count = 0
        rejected_plans: list[dict[str, Any]] = []
        plan = self.planner.plan(
            request,
            connector=self.connector,
            settings=self.settings,
            current_saved_jobs=current_saved_jobs,
            current_saved_companies=current_saved_companies,
            target_context=target_context,
            private_profile_context=private_profile_context,
            inventory_context=inventory_context,
        )
        if self.connector is None or not self._uses_default_planner:
            return plan
        critique = self.critic.review(
            request,
            connector=self.connector,
            settings=self.settings,
            plan=plan,
            current_saved_jobs=current_saved_jobs,
            inventory_context=inventory_context,
        )
        critic_attempt_count += 1
        if not critique.valid:
            rejected_plans.append(
                {
                    "issueCode": critique.issue_code,
                    "issueMessage": critique.issue_message,
                    "mode": plan.mode,
                    "modeRationale": plan.mode_rationale,
                }
            )
            if critique.corrected_plan is not None:
                plan = critique.corrected_plan
            else:
                planner_attempt_count += 1
                plan = self.planner.plan(
                    request,
                    connector=self.connector,
                    settings=self.settings,
                    current_saved_jobs=current_saved_jobs,
                    current_saved_companies=current_saved_companies,
                    target_context=target_context,
                    private_profile_context=private_profile_context,
                    inventory_context=inventory_context,
                    critique_context={
                        "issueCode": critique.issue_code,
                        "issueMessage": critique.issue_message,
                    },
                )
        return replace(
            plan,
            planner_attempt_count=planner_attempt_count,
            critic_attempt_count=critic_attempt_count,
            rejected_plans=tuple(rejected_plans),
            final_plan_status="planned",
        )

    def should_replan_for_pool_size(self, plan: DbJobSearchPlan, job_pool_size: int) -> bool:
        if is_jobs_list_ranking_plan(plan):
            return False
        if self.connector is None or not self._uses_default_planner:
            return False
        if plan.result_replan_count >= 1:
            return False
        if job_pool_size < plan.min_job_pool_size:
            return True
        return job_pool_size > plan.max_job_pool_size

    def apply_jobs_list_ranking_safety(self, plan: DbJobSearchPlan) -> tuple[DbJobSearchPlan, list[dict[str, Any]]]:
        if not is_jobs_list_ranking_plan(plan):
            return plan, []
        input_cap = max(plan.max_job_pool_size, self.settings.job_discovery_candidate_pool_limit or 0, 300)
        requested_count = plan.review_plan.requested_count or self.settings.job_discovery_save_limit
        corrections: list[dict[str, Any]] = []
        corrected_plan = plan
        if (
            plan.mode != "jobs_list_review"
            or plan.job_scope != "candidate_jobs_list"
            or plan.use_followed_company_boards
            or plan.proposed_adzuna_signatures
            or plan.existing_adzuna_signature_ids_to_refresh
            or plan.review_plan.allow_rejections
        ):
            corrections.append(
                {
                    "type": "forced_jobs_list_ranking_safety",
                    "originalMode": plan.mode,
                    "originalJobScope": plan.job_scope,
                    "clearedSyncPlan": bool(
                        plan.use_followed_company_boards
                        or plan.proposed_adzuna_signatures
                        or plan.existing_adzuna_signature_ids_to_refresh
                    ),
                }
            )
            corrected_plan = replace(
                corrected_plan,
                mode="jobs_list_review",
                job_scope="candidate_jobs_list",
                use_followed_company_boards=False,
                proposed_adzuna_signatures=(),
                existing_adzuna_signature_ids_to_refresh=(),
                sync_plan_rationale="No sync is allowed for jobs-list ranking.",
                review_plan=replace(
                    corrected_plan.review_plan,
                    allow_rejections=False,
                    review_all_eligible_jobs=True,
                ),
            )
        queries: list[DbJobSearchQuery] = []
        for query in corrected_plan.queries:
            if query.limit <= requested_count:
                corrections.append(
                    {
                        "type": "expanded_jobs_list_ranking_input_cap",
                        "label": query.label,
                        "requestedRecommendationCount": requested_count,
                        "originalLimit": query.limit,
                        "expandedLimit": input_cap,
                    }
                )
                queries.append(replace(query, limit=input_cap))
            else:
                queries.append(query)
        if not corrections:
            return corrected_plan, []
        return replace(corrected_plan, queries=tuple(queries), max_job_pool_size=max(corrected_plan.max_job_pool_size, input_cap)), corrections

    def replan_from_execution(
        self,
        request: JobDiscoveryRequest,
        *,
        plan: DbJobSearchPlan,
        current_saved_jobs: list[dict[str, Any]],
        current_saved_companies: list[dict[str, Any]],
        target_context: dict[str, Any],
        private_profile_context: dict[str, Any],
        inventory_context: dict[str, Any],
        execution_facts: dict[str, Any],
    ) -> DbJobSearchPlan:
        revised = self.planner.plan(
            request,
            connector=self.connector,
            settings=self.settings,
            current_saved_jobs=current_saved_jobs,
            current_saved_companies=current_saved_companies,
            target_context=target_context,
            private_profile_context=private_profile_context,
            inventory_context=inventory_context,
            execution_facts=execution_facts,
        )
        return replace(
            revised,
            planner_attempt_count=plan.planner_attempt_count + 1,
            critic_attempt_count=plan.critic_attempt_count,
            rejected_plans=plan.rejected_plans,
            final_plan_status="replanned",
            result_replan_count=plan.result_replan_count + 1,
            result_replan_reason=str(execution_facts.get("reason") or "pool_size"),
        )

    def mark_planning_started(self, run: JobSearchRun) -> None:
        run.search_mode = "db_backed"
        run.provider_names = ["model_planner"]
        run.status = "running"
        run.started_at = run.started_at or datetime.now(UTC)
        run.error = None
        run.run_diagnostics_json = {
            "planner": {
                "status": "running",
                "modelUsed": True,
                "planningFailed": False,
            },
            "jobSync": {"runs": [], "runCount": 0, "rawResultCount": 0, "normalizedCount": 0, "createdCount": 0, "updatedCount": 0, "completedCount": 0, "failedCount": 0},
            "databaseQueries": {"queries": [], "uniqueJobPoolCount": 0, "totalRowsMatched": 0},
            "modelReview": {
                "uniqueJobsInPool": 0,
                "jobsReviewedByModel": 0,
                "addedToCandidateJobsList": 0,
                "recordedModelRejections": 0,
                "selectedJobsLabel": "Selected/recommended jobs",
                "modelReviewCompleted": False,
            },
        }
        self.session.commit()

    def ensure_inventory(self, *, candidate_profile_id: str, plan: DbJobSearchPlan) -> tuple[Any, ...]:
        if is_jobs_list_ranking_plan(plan):
            self._last_planned_adzuna_signature_ids = []
            self._last_planned_adzuna_signature_actions = {}
            self._last_existing_adzuna_signature_ids = []
            return ()
        results: list[Any] = []
        self._last_planned_adzuna_signature_ids = []
        self._last_planned_adzuna_signature_actions = {}
        self._last_existing_adzuna_signature_ids = list(plan.existing_adzuna_signature_ids_to_refresh)
        existing_signature_ids = set(self.session.scalars(select(JobSyncSignature.id)).all())
        if plan.use_followed_company_boards:
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
        if plan.existing_adzuna_signature_ids_to_refresh:
            results.extend(
                sync_adzuna_signatures(
                    self.session,
                    settings=self.settings,
                    signature_ids=list(plan.existing_adzuna_signature_ids_to_refresh),
                    enabled_only=False,
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
            self._last_planned_adzuna_signature_ids.append(signature.id)
            self._last_planned_adzuna_signature_actions[signature.id] = "updated" if signature.id in existing_signature_ids else "created"
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

    def complete_planning_failure_run(self, run: JobSearchRun, error: DbJobSearchPlanningError) -> CandidateDiscoveryResult:
        plan = DbJobSearchPlan(queries=())
        planner = error.diagnostics.get("planner") if isinstance(error.diagnostics.get("planner"), dict) else {}
        planner_diagnostics = {
            "status": "failed",
            "modelUsed": planner.get("modelUsed", True),
            "planningFailed": True,
            "error": planner.get("error") or str(error),
            "errorDetail": planner.get("errorDetail"),
        }
        diagnostics = {
            "planner": planner_diagnostics,
            "jobSync": {"runs": [], "runCount": 0, "rawResultCount": 0, "normalizedCount": 0, "createdCount": 0, "updatedCount": 0, "completedCount": 0, "failedCount": 0},
            "databaseQueries": {"queries": [], "uniqueJobPoolCount": 0, "totalRowsMatched": 0},
            "modelReview": {
                "uniqueJobsInPool": 0,
                "jobsReviewedByModel": 0,
                "addedToCandidateJobsList": 0,
                "recordedModelRejections": 0,
                "selectedJobsLabel": "Selected/recommended jobs",
                "modelReviewCompleted": False,
                "modelReviewFailureReason": "Model search planning did not complete.",
            },
            "noJobsAddedReason": "model_planning_failed",
            "addedJobIds": [],
            "addedJobListingIds": [],
        }
        run.search_plan_json = {"planningFailed": True}
        run.search_mode = "db_backed"
        run.provider_names = ["model_planner"]
        run.status = "failed"
        run.completed_at = datetime.now(UTC)
        run.error = "Model search planning did not complete."
        run.total_provider_results = 0
        run.candidate_pool_count = 0
        run.candidate_count_after_dedupe = 0
        run.model_selected_count = 0
        run.saved_count = 0
        run.updated_existing_count = 0
        run.duplicate_count = 0
        run.skipped_count = 0
        run.provider_error_count = 0
        run.run_diagnostics_json = diagnostics
        self.session.flush()
        return CandidateDiscoveryResult(
            assistant_message="Model search planning did not complete, so I did not run Job Sync, database search, or job review.",
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

    def build_planner_inventory_context(self, *, current_saved_jobs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        signatures = list(
            self.session.scalars(
                select(JobSyncSignature)
                .where(JobSyncSignature.provider_name == "adzuna")
                .order_by(JobSyncSignature.updated_at.desc())
                .limit(25)
            )
        )
        recent_runs = list(
            self.session.scalars(
                select(JobSyncRun)
                .order_by(JobSyncRun.completed_at.desc().nullslast(), JobSyncRun.started_at.desc())
                .limit(25)
            )
        )
        recent_db_query_runs = list(
            self.session.scalars(
                select(JobSearchQueryRun)
                .where(JobSearchQueryRun.provider_name == "database")
                .order_by(JobSearchQueryRun.created_at.desc())
                .limit(50)
            )
        )
        provider_counts = {
            provider: int(count)
            for provider, count in self.session.execute(
                select(JobListingSource.source_provider, func.count(func.distinct(JobListing.id)))
                .join(JobListing, JobListingSource.job_listing_id == JobListing.id)
                .where(JobListing.is_active.is_(True), JobListing.closed_at.is_(None))
                .group_by(JobListingSource.source_provider)
            )
        }
        locations = [
            value
            for value in self.session.scalars(
                select(JobListing.location_display)
                .where(JobListing.location_display.is_not(None), JobListing.is_active.is_(True), JobListing.closed_at.is_(None))
                .distinct()
                .limit(20)
            )
            if value
        ]
        top_companies = [
            {"companyName": company, "activeJobCount": int(count)}
            for company, count in self.session.execute(
                select(JobListing.company_name, func.count(JobListing.id))
                .where(JobListing.company_name.is_not(None), JobListing.is_active.is_(True), JobListing.closed_at.is_(None))
                .group_by(JobListing.company_name)
                .order_by(func.count(JobListing.id).desc())
                .limit(20)
            )
            if company
        ]
        return {
            "existingAdzunaSignatures": [serialize_signature_for_planner(signature) for signature in signatures],
            "recentJobSyncRuns": [serialize_sync_run_for_planner(run) for run in recent_runs],
            "recentDbQueryRuns": [serialize_db_query_run_for_planner(run) for run in recent_db_query_runs],
            "syncedInventorySummary": {
                "activeJobListingCount": sum(provider_counts.values()),
                "providers": provider_counts,
                "locations": locations,
                "topCompanies": top_companies,
            },
            "currentJobsListSummary": {
                "visibleJobsListCount": len(current_saved_jobs or []),
                "sample": (current_saved_jobs or [])[:10],
            },
        }

    def build_planner_diagnostics(self, plan: DbJobSearchPlan, job_sync_results: list[Any]) -> dict[str, Any]:
        results_by_signature_id = {
            result.request.job_sync_signature_id: result
            for result in job_sync_results
            if getattr(getattr(result, "request", None), "job_sync_signature_id", None)
        }
        proposed_ids = list(getattr(self, "_last_planned_adzuna_signature_ids", []))
        proposed_actions = dict(getattr(self, "_last_planned_adzuna_signature_actions", {}))
        existing_ids = list(getattr(self, "_last_existing_adzuna_signature_ids", plan.existing_adzuna_signature_ids_to_refresh))
        signatures = {
            signature.id: signature
            for signature in self.session.scalars(
                select(JobSyncSignature).where(
                    JobSyncSignature.id.in_(
                        [
                            *[signature_id for signature_id in existing_ids if signature_id],
                            *[signature_id for signature_id in proposed_ids if signature_id],
                        ]
                    )
                )
            ).all()
        } if (existing_ids or proposed_ids) else {}
        return {
            "status": "planned",
            "modelUsed": True,
            "planningFailed": False,
            "mode": plan.mode,
            "modeRationale": plan.mode_rationale,
            "jobScope": plan.job_scope,
            "syncPlanRationale": plan.sync_plan_rationale,
            "reviewTask": plan.review_plan.task,
            "reviewPlanRationale": plan.review_plan.rationale,
            "requestedRecommendationCount": plan.review_plan.requested_count,
            "allowRejections": plan.review_plan.allow_rejections,
            "reviewAllEligibleJobs": plan.review_plan.review_all_eligible_jobs,
            "useFollowedCompanyBoards": plan.use_followed_company_boards,
            "plannerAttemptCount": plan.planner_attempt_count,
            "criticAttemptCount": plan.critic_attempt_count,
            "rejectedPlans": list(plan.rejected_plans),
            "finalPlanStatus": plan.final_plan_status,
            "resultReplanCount": plan.result_replan_count,
            "resultReplanReason": plan.result_replan_reason,
            "plannedSyncSignatures": [serialize_signature_for_diagnostics(signatures.get(signature_id), results_by_signature_id.get(signature_id), action=proposed_actions.get(signature_id, "updated")) for signature_id in proposed_ids if signatures.get(signature_id)],
            "existingSyncSignaturesSelected": [serialize_signature_for_diagnostics(signatures.get(signature_id), results_by_signature_id.get(signature_id), action="reused") for signature_id in existing_ids if signatures.get(signature_id)],
            "plannedDbQueries": [serialize_query_for_diagnostics(query) for query in plan.queries],
        }

    def persist_db_query_runs(
        self,
        job_search_run_id: str,
        queries: tuple[DbJobSearchQuery, ...],
        query_counts: tuple[tuple[str, int], ...],
        *,
        deduped_count: int,
    ) -> None:
        counts_by_label = {label: count for label, count in query_counts}
        for query in queries:
            count = int(counts_by_label.get(query.label, 0))
            self.session.add(
                JobSearchQueryRun(
                    job_search_run_id=job_search_run_id,
                    provider_name="database",
                    query=query.label,
                    company_name=", ".join(query.company_names_any[:3]) or None,
                    location=summarize_query_location(query),
                    page=None,
                    total_matches=count,
                    raw_result_count=count,
                    normalized_result_count=count,
                    deduped_result_count=deduped_count,
                    candidate_count_after_filters=count,
                    error=None,
                )
            )
        self.session.flush()

    def load_existing_saved_links_for_recommendations(self, candidate_profile_id: str, job_listing_ids: list[str]) -> list[CandidateSavedJob]:
        order = {job_listing_id: index for index, job_listing_id in enumerate(job_listing_ids)}
        if not order:
            return []
        links = list(
            self.session.scalars(
                select(CandidateSavedJob)
                .where(
                    CandidateSavedJob.candidate_profile_id == candidate_profile_id,
                    CandidateSavedJob.job_listing_id.in_(order),
                )
                .options(selectinload(CandidateSavedJob.job_listing).selectinload(JobListing.sources))
            ).all()
        )
        return sorted(links, key=lambda link: order.get(link.job_listing_id or "", len(order)))

    def build_pool_entries(self, jobs: list[JobListing], *, candidate_profile_id: str) -> list[JobPoolEntry]:
        providers_by_job_id: dict[str, tuple[str, ...]] = {}
        saved_job_ids_by_listing_id: dict[str, str] = {}
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
            saved_links = self.session.scalars(
                select(CandidateSavedJob).where(
                    CandidateSavedJob.candidate_profile_id == candidate_profile_id,
                    CandidateSavedJob.job_listing_id.in_([job.id for job in jobs]),
                )
            ).all()
            saved_job_ids_by_listing_id = {link.job_listing_id: link.id for link in saved_links if link.job_listing_id}
        return [
            replace(
                job_listing_to_pool_entry(job, source_providers=providers_by_job_id.get(job.id, ())),
                saved_job_id=saved_job_ids_by_listing_id.get(job.id),
            )
            for job in jobs
        ]

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
        "mode": plan.mode,
        "modeRationale": plan.mode_rationale,
        "jobScope": plan.job_scope,
        "syncPlan": {
            "useFollowedCompanyBoards": plan.use_followed_company_boards,
            "proposedAdzunaSignatures": list(plan.proposed_adzuna_signatures),
            "existingAdzunaSignatureIdsToRefresh": list(plan.existing_adzuna_signature_ids_to_refresh),
            "rationale": plan.sync_plan_rationale,
        },
        "dbSearchPlan": {
            "queries": [json_safe(asdict(query)) for query in plan.queries],
        },
        "reviewPlan": {
            "task": plan.review_plan.task,
            "requestedCount": plan.review_plan.requested_count,
            "allowRejections": plan.review_plan.allow_rejections,
            "reviewAllEligibleJobs": plan.review_plan.review_all_eligible_jobs,
            "rationale": plan.review_plan.rationale,
        },
        "replanRules": {
            "minJobPoolSize": plan.min_job_pool_size,
            "maxJobPoolSize": plan.max_job_pool_size,
            "maxJobsForModelReview": plan.max_jobs_for_model_review,
        },
        "plannerAttemptCount": plan.planner_attempt_count,
        "criticAttemptCount": plan.critic_attempt_count,
        "rejectedPlans": list(plan.rejected_plans),
        "finalPlanStatus": plan.final_plan_status,
        "resultReplanCount": plan.result_replan_count,
        "resultReplanReason": plan.result_replan_reason,
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


def serialize_signature_for_planner(signature: JobSyncSignature) -> dict[str, Any]:
    return {
        "id": signature.id,
        "syncKey": signature.sync_key,
        "queryText": signature.query_text,
        "queryKind": signature.query_kind,
        "displayLocation": signature.display_location,
        "providerCountry": signature.provider_country,
        "providerWhere": signature.provider_where,
        "enabled": signature.enabled,
        "verificationStatus": signature.verification_status,
        "lastCompletedAt": signature.last_completed_at.isoformat() if signature.last_completed_at else None,
        "lastRawResultCount": signature.last_raw_result_count,
        "lastNormalizedCount": signature.last_normalized_count,
    }


def serialize_sync_run_for_planner(run: JobSyncRun) -> dict[str, Any]:
    return {
        "syncKey": run.sync_key,
        "providerName": run.provider_name,
        "status": run.status,
        "rawResultCount": run.raw_result_count,
        "normalizedCount": run.normalized_count,
        "createdCount": run.created_count,
        "updatedCount": run.updated_count,
        "completedAt": run.completed_at.isoformat() if run.completed_at else None,
    }


def serialize_db_query_run_for_planner(run: JobSearchQueryRun) -> dict[str, Any]:
    diagnostics = run.job_search_run.run_diagnostics_json if getattr(run, "job_search_run", None) is not None else {}
    return {
        "jobSearchRunId": run.job_search_run_id,
        "label": run.query,
        "criteriaSummary": run.query,
        "resultCount": run.total_matches,
        "createdAt": run.created_at.isoformat() if run.created_at else None,
        "noJobsAddedReason": diagnostics.get("noJobsAddedReason") if isinstance(diagnostics, dict) else None,
    }


def serialize_signature_for_diagnostics(signature: JobSyncSignature | None, result: Any | None, *, action: str) -> dict[str, Any]:
    if signature is None:
        return {}
    result_status = getattr(result, "status", None)
    display_action = "failed" if result_status == "failed" else "skipped" if str(result_status or "").startswith("skipped") else action
    return {
        "id": signature.id,
        "syncKey": signature.sync_key,
        "providerName": signature.provider_name,
        "queryText": signature.query_text,
        "queryKind": signature.query_kind,
        "displayLocation": signature.display_location,
        "providerCountry": signature.provider_country,
        "providerWhere": signature.provider_where,
        "maxPages": signature.max_pages,
        "resultsPerPage": signature.results_per_page,
        "enabled": signature.enabled,
        "verificationStatus": signature.verification_status,
        "action": display_action,
        "syncRunStatus": result_status,
        "raw": getattr(result, "raw_result_count", None),
        "normalized": getattr(result, "normalized_count", None),
        "created": getattr(result, "created_count", None),
        "updated": getattr(result, "updated_count", None),
    }


def serialize_query_for_diagnostics(query: DbJobSearchQuery) -> dict[str, Any]:
    return {
        "label": query.label,
        "titleTermsAny": list(query.title_terms_any),
        "titleTermsAll": list(query.title_terms_all),
        "titleTermsExclude": list(query.title_terms_exclude),
        "descriptionTermsAny": list(query.description_terms_any),
        "descriptionTermsAll": list(query.description_terms_all),
        "descriptionTermsExclude": list(query.description_terms_exclude),
        "companyIdsAny": list(query.company_ids_any),
        "companyNamesAny": list(query.company_names_any),
        "companyNamesExclude": list(query.company_names_exclude),
        "sourceProvidersAny": list(query.source_providers_any),
        "atsBoardTokensAny": list(query.ats_board_tokens_any),
        "locationTargetIdsAny": list(query.location_target_ids_any),
        "locationCountriesAny": list(query.location_countries_any),
        "locationRegionsAny": list(query.location_regions_any),
        "locationCitiesAny": list(query.location_cities_any),
        "locationMetrosAny": list(query.location_metros_any),
        "locationDisplayTermsAny": list(query.location_display_terms_any),
        "remoteWorkModesAny": list(query.remote_work_modes_any),
        "employmentTypesAny": list(query.employment_types_any),
        "salaryCurrency": query.salary_currency,
        "salaryMinAtLeast": query.salary_min_at_least,
        "sourceStatusesAny": list(query.source_statuses_any),
        "freshnessDays": query.freshness_days,
        "limit": query.limit,
        "activeOnly": query.active_only,
        "includeModelRejected": query.include_model_rejected,
        "orderBy": query.order_by,
    }


def summarize_query_location(query: DbJobSearchQuery) -> str | None:
    parts = [
        *query.location_countries_any,
        *query.location_regions_any,
        *query.location_cities_any,
        *query.location_metros_any,
        *query.location_display_terms_any,
    ]
    return ", ".join(str(part) for part in parts if str(part).strip()) or None


def selected_jobs_label_for_scope(scope: str) -> str:
    if scope == "candidate_jobs_list":
        return "Recommended existing jobs"
    if scope == "all_accessible_jobs":
        return "Selected/recommended jobs"
    return "Added to jobs list"


def is_jobs_list_ranking_plan(plan: DbJobSearchPlan) -> bool:
    return plan.review_plan.task == "rank_existing_jobs"
