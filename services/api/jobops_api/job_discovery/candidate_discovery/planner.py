from __future__ import annotations

import json
import queue
import threading
from dataclasses import dataclass, field
from typing import Any

from ...model_connector import ModelConnector, ModelMessage, ModelRequest, ModelResponse
from ...settings import Settings
from ..models import JobDiscoveryRequest
from ..provider_utils import safe_log_preview
from .models import MODE_TO_SCOPE, DbJobSearchPlan, DbJobSearchQuery, DiscoveryMode, ReviewPlan
from .prompts import DB_JOB_SEARCH_PLAN_CRITIC_SYSTEM_PROMPT, DB_JOB_SEARCH_PLANNER_SYSTEM_PROMPT


ALLOWED_DISCOVERY_MODES = set(MODE_TO_SCOPE)


class DbJobSearchPlanningError(Exception):
    def __init__(self, message: str, *, diagnostics: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics or {}


@dataclass(frozen=True)
class DbJobSearchPlannerResult:
    status: str
    plan: DbJobSearchPlan | None = None
    error: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateDiscoveryPlanCritique:
    valid: bool
    issue_code: str | None = None
    issue_message: str | None = None
    corrected_plan: DbJobSearchPlan | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


class DbJobSearchPlanner:
    def plan(
        self,
        request: JobDiscoveryRequest,
        *,
        connector: ModelConnector | None,
        settings: Settings,
        current_saved_jobs: list[dict[str, Any]],
        current_saved_companies: list[dict[str, Any]],
        target_context: dict[str, Any],
        private_profile_context: dict[str, Any],
        inventory_context: dict[str, Any] | None = None,
        critique_context: dict[str, Any] | None = None,
        execution_facts: dict[str, Any] | None = None,
    ) -> DbJobSearchPlan:
        if connector is None:
            raise DbJobSearchPlanningError(
                "Model search planning did not complete because no model connector is configured.",
                diagnostics={"planner": {"status": "failed", "modelUsed": False, "planningFailed": True, "error": "missing_model_connector"}},
            )
        model_request = self.build_model_request(
            request,
            current_saved_jobs=current_saved_jobs,
            current_saved_companies=current_saved_companies,
            target_context=target_context,
            private_profile_context=private_profile_context,
            inventory_context=inventory_context,
            critique_context=critique_context,
            execution_facts=execution_facts,
        )
        try:
            response = generate_with_timeout(
                connector,
                model_request,
                timeout_seconds=settings.llm_request_timeout_seconds,
            )
            return parse_db_search_plan(response.text)
        except DbJobSearchPlanningError:
            raise
        except Exception as exc:
            raise DbJobSearchPlanningError(
                "Model search planning did not complete.",
                diagnostics={
                    "planner": {
                        "status": "failed",
                        "modelUsed": True,
                        "planningFailed": True,
                        "error": type(exc).__name__,
                        "errorDetail": safe_log_preview(str(exc), limit=240) or type(exc).__name__,
                    }
                },
            ) from exc

    def build_model_request(
        self,
        request: JobDiscoveryRequest,
        *,
        current_saved_jobs: list[dict[str, Any]],
        current_saved_companies: list[dict[str, Any]],
        target_context: dict[str, Any],
        private_profile_context: dict[str, Any],
        inventory_context: dict[str, Any] | None = None,
        critique_context: dict[str, Any] | None = None,
        execution_facts: dict[str, Any] | None = None,
    ) -> ModelRequest:
        payload = {
            "latestUserMessage": request.latest_user_message,
            "currentSavedJobs": current_saved_jobs[:50],
            "currentSavedCompanies": current_saved_companies[:50],
            "targetContext": target_context,
            "privateProfileContext": private_profile_context,
            "inventoryContext": inventory_context or {},
            "allowedDiscoveryModes": list(MODE_TO_SCOPE.keys()),
            "broadeningRules": {
                "broadenByRemovingCriteria": True,
                "latestMessageOutranksStoredProfile": True,
                "askOnlyBeforeRelaxingExplicitDealbreakers": True,
            },
        }
        if critique_context:
            payload["critiqueContext"] = critique_context
        if execution_facts:
            payload["executionFacts"] = execution_facts
        return ModelRequest(
            task="candidate_db_job_search_planning",
            temperature=0.1,
            max_output_tokens=5000,
            response_mime_type="application/json",
            search_grounding=False,
            metadata={"feature": "candidate_db_job_search_planning"},
            messages=[
                ModelMessage(role="system", content=DB_JOB_SEARCH_PLANNER_SYSTEM_PROMPT),
                ModelMessage(role="user", content=json.dumps(payload, sort_keys=True, default=str)),
            ],
        )


class CandidateDiscoveryPlanCritic:
    def review(
        self,
        request: JobDiscoveryRequest,
        *,
        connector: ModelConnector | None,
        settings: Settings,
        plan: DbJobSearchPlan,
        current_saved_jobs: list[dict[str, Any]],
        current_saved_companies: list[dict[str, Any]],
        inventory_context: dict[str, Any],
    ) -> CandidateDiscoveryPlanCritique:
        if connector is None:
            raise DbJobSearchPlanningError(
                "Model plan critique did not complete because no model connector is configured.",
                diagnostics={"planner": {"status": "failed", "modelUsed": False, "planningFailed": True, "error": "missing_model_connector"}},
            )
        model_request = ModelRequest(
            task="candidate_db_job_plan_critique",
            temperature=0,
            max_output_tokens=5000,
            response_mime_type="application/json",
            search_grounding=False,
            metadata={"feature": "candidate_db_job_plan_critique"},
            messages=[
                ModelMessage(role="system", content=DB_JOB_SEARCH_PLAN_CRITIC_SYSTEM_PROMPT),
                ModelMessage(
                    role="user",
                    content=json.dumps(
                        {
                            "latestUserMessage": request.latest_user_message,
                            "currentJobsListSummary": summarize_jobs_list(current_saved_jobs),
                            "currentSavedCompaniesSummary": summarize_saved_companies(current_saved_companies),
                            "inventoryContext": inventory_context,
                            "proposedPlan": serialize_plan_for_model(plan),
                        },
                        sort_keys=True,
                        default=str,
                    ),
                ),
            ],
        )
        try:
            response = generate_with_timeout(connector, model_request, timeout_seconds=settings.llm_request_timeout_seconds)
            return parse_plan_critique(response.text)
        except DbJobSearchPlanningError:
            raise
        except Exception as exc:
            raise DbJobSearchPlanningError(
                "Model plan critique did not complete.",
                diagnostics={
                    "planner": {
                        "status": "failed",
                        "modelUsed": True,
                        "planningFailed": True,
                        "error": type(exc).__name__,
                        "errorDetail": safe_log_preview(str(exc), limit=240) or type(exc).__name__,
                    }
                },
            ) from exc


def parse_db_search_plan(raw_text: str) -> DbJobSearchPlan:
    try:
        parsed = json.loads(extract_first_json(raw_text))
    except Exception as exc:
        raise DbJobSearchPlanningError(
            "Model search planning returned invalid JSON.",
            diagnostics={"planner": {"status": "failed", "modelUsed": True, "planningFailed": True, "error": "invalid_json"}},
        ) from exc
    plan = parsed.get("searchPlan", parsed)
    mode = str(plan.get("mode") or "").strip()
    if mode not in ALLOWED_DISCOVERY_MODES:
        raise DbJobSearchPlanningError(
            "Model search planning did not include a valid discovery mode.",
            diagnostics={"planner": {"status": "failed", "modelUsed": True, "planningFailed": True, "error": "invalid_mode"}},
        )
    sync_plan = plan.get("syncPlan") if isinstance(plan.get("syncPlan"), dict) else {}
    db_search_plan = plan.get("dbSearchPlan") if isinstance(plan.get("dbSearchPlan"), dict) else {}
    raw_queries = db_search_plan.get("queries", [])
    if mode == "direct_job_url" and (not isinstance(raw_queries, list) or not raw_queries):
        raw_queries = []
    elif not isinstance(raw_queries, list) or not raw_queries:
        raise DbJobSearchPlanningError(
            "Model search planning did not include database queries.",
            diagnostics={"planner": {"status": "failed", "modelUsed": True, "planningFailed": True, "error": "missing_queries"}},
        )
    queries = tuple(parse_query(item) for item in raw_queries if isinstance(item, dict))
    if not queries and mode != "direct_job_url":
        raise DbJobSearchPlanningError(
            "Model search planning did not include valid database queries.",
            diagnostics={"planner": {"status": "failed", "modelUsed": True, "planningFailed": True, "error": "invalid_queries"}},
        )
    rules = plan.get("replanRules") or {}
    rules = plan.get("replanRules") if isinstance(plan.get("replanRules"), dict) else {}
    review_plan = parse_review_plan(plan.get("reviewPlan"), mode=mode)
    return DbJobSearchPlan(
        mode=mode,  # type: ignore[arg-type]
        mode_rationale=clean_optional_text(plan.get("modeRationale")),
        job_scope=MODE_TO_SCOPE[mode],
        queries=queries,
        min_job_pool_size=int(rules.get("minJobPoolSize") or 40),
        max_job_pool_size=int(rules.get("maxJobPoolSize") or 300),
        max_jobs_for_model_review=int(rules.get("maxJobsForModelReview") or 80),
        use_followed_company_boards=bool(sync_plan.get("useFollowedCompanyBoards", False)),
        sync_plan_rationale=clean_optional_text(sync_plan.get("rationale")),
        proposed_adzuna_signatures=tuple(sync_plan.get("proposedAdzunaSignatures") or ()),
        existing_adzuna_signature_ids_to_refresh=tuple(
            str(item) for item in sync_plan.get("existingAdzunaSignatureIdsToRefresh", []) if str(item).strip()
        ),
        review_plan=review_plan,
    )


def parse_review_plan(raw: object, *, mode: str) -> ReviewPlan:
    if isinstance(raw, dict):
        task = str(raw.get("task") or "").strip()
        if task not in {"select_new_jobs", "rank_existing_jobs"}:
            task = "rank_existing_jobs" if mode == "jobs_list_review" else "select_new_jobs"
        requested_count = parse_positive_int(raw.get("requestedCount"))
        return ReviewPlan(
            task=task,  # type: ignore[arg-type]
            requested_count=requested_count,
            allow_rejections=bool(raw.get("allowRejections", task != "rank_existing_jobs")),
            review_all_eligible_jobs=bool(raw.get("reviewAllEligibleJobs", task == "rank_existing_jobs")),
            rationale=clean_optional_text(raw.get("rationale")),
        )
    if mode == "jobs_list_review":
        return ReviewPlan(task="rank_existing_jobs", allow_rejections=False, review_all_eligible_jobs=True)
    return ReviewPlan()


def parse_positive_int(value: object) -> int | None:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def parse_query(raw: dict[str, Any]) -> DbJobSearchQuery:
    freshness_days = raw.get("freshnessDays")
    order_by = str(raw.get("orderBy") or "last_seen_at_desc")
    if order_by not in {"last_seen_at_desc", "posting_date_desc", "source_updated_at_desc"}:
        order_by = "last_seen_at_desc"
    return DbJobSearchQuery(
        label=str(raw.get("label") or "DB synced job search"),
        active_only=bool(raw.get("activeOnly", True)),
        title_terms_any=tuple(raw.get("titleTermsAny") or ()),
        title_terms_all=tuple(raw.get("titleTermsAll") or ()),
        title_terms_exclude=tuple(raw.get("titleTermsExclude") or ()),
        description_terms_any=tuple(raw.get("descriptionTermsAny") or ()),
        description_terms_all=tuple(raw.get("descriptionTermsAll") or ()),
        description_terms_exclude=tuple(raw.get("descriptionTermsExclude") or ()),
        company_ids_any=tuple(raw.get("companyIdsAny") or ()),
        company_names_any=tuple(raw.get("companyNamesAny") or ()),
        company_names_exclude=tuple(raw.get("companyNamesExclude") or ()),
        source_providers_any=tuple(raw.get("sourceProvidersAny") or ()),
        ats_board_tokens_any=tuple(raw.get("atsBoardTokensAny") or ()),
        location_target_ids_any=tuple(raw.get("locationTargetIdsAny") or ()),
        location_countries_any=tuple(raw.get("locationCountriesAny") or ()),
        location_regions_any=tuple(raw.get("locationRegionsAny") or ()),
        location_cities_any=tuple(raw.get("locationCitiesAny") or ()),
        location_metros_any=tuple(raw.get("locationMetrosAny") or ()),
        location_display_terms_any=tuple(raw.get("locationDisplayTermsAny") or ()),
        remote_work_modes_any=tuple(raw.get("remoteWorkModesAny") or ()),
        employment_types_any=tuple(raw.get("employmentTypesAny") or ()),
        salary_currency=raw.get("salaryCurrency"),
        salary_min_at_least=raw.get("salaryMinAtLeast"),
        source_statuses_any=tuple(raw.get("sourceStatusesAny") or ("active",)),
        freshness_days=int(freshness_days) if freshness_days else None,
        include_model_rejected=bool(raw.get("includeModelRejected", False)),
        limit=int(raw.get("limit") or 300),
        order_by=order_by,
    )


def parse_plan_critique(raw_text: str) -> CandidateDiscoveryPlanCritique:
    try:
        parsed = json.loads(extract_first_json(raw_text))
    except Exception as exc:
        raise DbJobSearchPlanningError(
            "Model plan critique returned invalid JSON.",
            diagnostics={"planner": {"status": "failed", "modelUsed": True, "planningFailed": True, "error": "invalid_critique_json"}},
        ) from exc
    valid = bool(parsed.get("valid"))
    issue_code = clean_optional_text(parsed.get("issueCode"))
    issue_message = clean_optional_text(parsed.get("issueMessage"))
    corrected_plan = None
    raw_corrected = parsed.get("correctedPlan")
    if isinstance(raw_corrected, dict):
        corrected_plan = parse_db_search_plan(json.dumps(raw_corrected))
    return CandidateDiscoveryPlanCritique(
        valid=valid,
        issue_code=issue_code,
        issue_message=issue_message,
        corrected_plan=corrected_plan,
        diagnostics={
            "valid": valid,
            "issueCode": issue_code,
            "issueMessage": issue_message,
            "correctedPlanProvided": corrected_plan is not None,
        },
    )


def clean_optional_text(value: object) -> str | None:
    cleaned = " ".join(str(value or "").split()).strip()
    return cleaned or None


def serialize_plan_for_model(plan: DbJobSearchPlan) -> dict[str, Any]:
    return {
        "mode": plan.mode,
        "modeRationale": plan.mode_rationale,
        "syncPlan": {
            "useFollowedCompanyBoards": plan.use_followed_company_boards,
            "proposedAdzunaSignatures": list(plan.proposed_adzuna_signatures),
            "existingAdzunaSignatureIdsToRefresh": list(plan.existing_adzuna_signature_ids_to_refresh),
            "rationale": plan.sync_plan_rationale,
        },
        "dbSearchPlan": {
            "queries": [serialize_query_for_model(query) for query in plan.queries],
        },
        "reviewPlan": serialize_review_plan_for_model(plan.review_plan),
        "replanRules": {
            "minJobPoolSize": plan.min_job_pool_size,
            "maxJobPoolSize": plan.max_job_pool_size,
            "maxJobsForModelReview": plan.max_jobs_for_model_review,
        },
    }


def serialize_review_plan_for_model(review_plan: ReviewPlan) -> dict[str, Any]:
    return {
        "task": review_plan.task,
        "requestedCount": review_plan.requested_count,
        "allowRejections": review_plan.allow_rejections,
        "reviewAllEligibleJobs": review_plan.review_all_eligible_jobs,
        "rationale": review_plan.rationale,
    }


def serialize_query_for_model(query: DbJobSearchQuery) -> dict[str, Any]:
    return {
        "label": query.label,
        "activeOnly": query.active_only,
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
        "includeModelRejected": query.include_model_rejected,
        "limit": query.limit,
        "orderBy": query.order_by,
    }


def summarize_jobs_list(current_saved_jobs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "visibleJobsListCount": len(current_saved_jobs),
        "sample": current_saved_jobs[:10],
    }


def summarize_saved_companies(current_saved_companies: list[dict[str, Any]]) -> dict[str, Any]:
    syncable = [
        company
        for company in current_saved_companies
        if isinstance(company, dict)
        and (
            company.get("greenhouse_board_token")
            or company.get("greenhouseBoardToken")
            or "greenhouse" in json.dumps(company, default=str).casefold()
        )
    ]
    return {
        "savedCompanyCount": len(current_saved_companies),
        "greenhouseSyncableCompanyCount": len(syncable),
        "sample": current_saved_companies[:10],
    }


def extract_first_json(raw_text: str) -> str:
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Model response did not include a JSON object.")
    return raw_text[start : end + 1]


def generate_with_timeout(
    connector: ModelConnector,
    request: ModelRequest,
    *,
    timeout_seconds: float,
) -> ModelResponse:
    if timeout_seconds <= 0:
        return connector.generate(request)

    result_queue: queue.Queue[tuple[str, ModelResponse | BaseException]] = queue.Queue(maxsize=1)

    def target() -> None:
        try:
            result_queue.put(("response", connector.generate(request)))
        except BaseException as exc:
            result_queue.put(("error", exc))

    thread = threading.Thread(target=target, name="jobops-db-job-planner-model-call", daemon=True)
    thread.start()
    try:
        kind, value = result_queue.get(timeout=timeout_seconds)
    except queue.Empty as exc:
        raise TimeoutError(f"Model search planning exceeded {timeout_seconds:g}s timeout.") from exc
    if kind == "error":
        raise value
    return value
