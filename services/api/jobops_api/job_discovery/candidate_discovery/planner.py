from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ...model_connector import ModelConnector, ModelMessage, ModelRequest
from ...settings import Settings
from ..models import JobDiscoveryRequest
from .models import DbJobSearchPlan, DbJobSearchQuery
from .prompts import DB_JOB_SEARCH_PLANNER_SYSTEM_PROMPT


ALL_ACCESSIBLE_JOB_REQUEST_PHRASES = (
    "all jobs",
    "existing and new jobs",
    "new and saved jobs",
    "everything available",
)

EXISTING_JOB_LIST_REQUEST_PHRASES = (
    "show me the jobs",
    "which jobs did you find",
    "what jobs did you add",
    "show me the jobs you found",
    "show me my jobs",
    "show me my jobs list",
    "what is on my jobs list",
    "which saved jobs should i apply to",
    "show saved jobs",
    "my saved jobs",
    "jobs already on my list",
    "jobs i already saved",
    "review my jobs",
    "saved jobs",
    "jobs list",
)

EXISTING_JOB_LIST_REQUEST_PREFIXES = (
    "which jobs",
    "what jobs",
)

NEW_JOB_DISCOVERY_REQUEST_PHRASES = (
    "find jobs",
    "find new jobs",
    "give me jobs",
    "give me some jobs",
    "give me jobs to apply to",
    "find jobs to apply to",
    "show me some jobs",
    "find roles",
    "find me roles",
    "look for jobs",
    "discover jobs",
)


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
        )
        try:
            response = connector.generate(model_request)
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
    ) -> ModelRequest:
        payload = {
            "latestUserMessage": request.latest_user_message,
            "currentSavedJobs": current_saved_jobs[:50],
            "currentSavedCompanies": current_saved_companies[:50],
            "targetContext": target_context,
            "privateProfileContext": private_profile_context,
            "inventoryContext": inventory_context or {},
            "allowedJobScopes": ["new_to_candidate", "candidate_jobs_list", "all_accessible_jobs"],
            "broadeningRules": {
                "broadenByRemovingCriteria": True,
                "latestMessageOutranksStoredProfile": True,
                "askOnlyBeforeRelaxingExplicitDealbreakers": True,
            },
        }
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


def infer_scope(message: str) -> str:
    if is_all_accessible_jobs_request(message):
        return "all_accessible_jobs"
    if is_existing_jobs_list_request(message):
        return "candidate_jobs_list"
    return "new_to_candidate"


def is_all_accessible_jobs_request(message: str) -> bool:
    cleaned = normalize_scope_text(message)
    return phrase_matches(cleaned, ALL_ACCESSIBLE_JOB_REQUEST_PHRASES)


def is_existing_jobs_list_request(message: str) -> bool:
    cleaned = normalize_scope_text(message)
    if phrase_matches(cleaned, EXISTING_JOB_LIST_REQUEST_PHRASES):
        return True
    return any(cleaned == prefix or cleaned.startswith(f"{prefix} ") for prefix in EXISTING_JOB_LIST_REQUEST_PREFIXES)


def is_new_job_discovery_request(message: str) -> bool:
    cleaned = normalize_scope_text(message)
    return phrase_matches(cleaned, NEW_JOB_DISCOVERY_REQUEST_PHRASES)


def normalize_scope_text(message: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9+#.\s-]", " ", message.casefold()).split())


def phrase_matches(cleaned_message: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in cleaned_message for phrase in phrases)


def parse_db_search_plan(raw_text: str) -> DbJobSearchPlan:
    try:
        parsed = json.loads(extract_first_json(raw_text))
    except Exception as exc:
        raise DbJobSearchPlanningError(
            "Model search planning returned invalid JSON.",
            diagnostics={"planner": {"status": "failed", "modelUsed": True, "planningFailed": True, "error": "invalid_json"}},
        ) from exc
    plan = parsed.get("searchPlan", parsed)
    raw_queries = plan.get("queries", [])
    if not isinstance(raw_queries, list) or not raw_queries:
        raise DbJobSearchPlanningError(
            "Model search planning did not include database queries.",
            diagnostics={"planner": {"status": "failed", "modelUsed": True, "planningFailed": True, "error": "missing_queries"}},
        )
    queries = tuple(parse_query(item) for item in raw_queries if isinstance(item, dict))
    if not queries:
        raise DbJobSearchPlanningError(
            "Model search planning did not include valid database queries.",
            diagnostics={"planner": {"status": "failed", "modelUsed": True, "planningFailed": True, "error": "invalid_queries"}},
        )
    rules = plan.get("replanRules") or {}
    scope = str(plan.get("jobScope") or "new_to_candidate")
    if scope not in {"new_to_candidate", "candidate_jobs_list", "all_accessible_jobs"}:
        scope = "new_to_candidate"
    return DbJobSearchPlan(
        job_scope=scope,
        queries=queries,
        min_job_pool_size=int(rules.get("minJobPoolSize") or 40),
        max_job_pool_size=int(rules.get("maxJobPoolSize") or 300),
        max_jobs_for_model_review=int(rules.get("maxJobsForModelReview") or 80),
        proposed_adzuna_signatures=tuple(plan.get("proposedAdzunaSignatures") or ()),
        existing_adzuna_signature_ids_to_refresh=tuple(
            str(item) for item in plan.get("existingAdzunaSignatureIdsToRefresh", []) if str(item).strip()
        ),
    )


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


def extract_first_json(raw_text: str) -> str:
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Model response did not include a JSON object.")
    return raw_text[start : end + 1]
