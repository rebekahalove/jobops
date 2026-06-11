from __future__ import annotations

import json
import re
from typing import Any

from ...model_connector import ModelConnector, ModelMessage, ModelRequest
from ...settings import Settings
from ..models import JobDiscoveryRequest
from .models import DbJobSearchPlan, DbJobSearchQuery
from .prompts import DB_JOB_SEARCH_PLANNER_SYSTEM_PROMPT


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
    ) -> DbJobSearchPlan:
        model_request = self.build_model_request(
            request,
            current_saved_jobs=current_saved_jobs,
            current_saved_companies=current_saved_companies,
            target_context=target_context,
            private_profile_context=private_profile_context,
        )
        if connector is not None:
            try:
                response = connector.generate(model_request)
                return parse_db_search_plan(response.text)
            except Exception:
                pass
        return deterministic_plan_from_request(request)

    def build_model_request(
        self,
        request: JobDiscoveryRequest,
        *,
        current_saved_jobs: list[dict[str, Any]],
        current_saved_companies: list[dict[str, Any]],
        target_context: dict[str, Any],
        private_profile_context: dict[str, Any],
    ) -> ModelRequest:
        payload = {
            "latestUserMessage": request.latest_user_message,
            "currentSavedJobs": current_saved_jobs[:50],
            "currentSavedCompanies": current_saved_companies[:50],
            "targetContext": target_context,
            "privateProfileContext": private_profile_context,
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


def deterministic_plan_from_request(request: JobDiscoveryRequest) -> DbJobSearchPlan:
    message = request.latest_user_message or ""
    scope = infer_scope(message)
    terms = extract_search_terms(message)
    query = DbJobSearchQuery(
        label="DB-backed synced job search",
        title_terms_any=tuple(terms[:8]),
        description_terms_any=tuple(terms[:12]),
        freshness_days=120,
        limit=300,
    )
    return DbJobSearchPlan(job_scope=scope, queries=(query,), max_job_pool_size=300, max_jobs_for_model_review=80)


def infer_scope(message: str) -> str:
    cleaned = message.casefold()
    if any(phrase in cleaned for phrase in ("saved jobs", "my jobs", "jobs list", "already saved", "apply to")):
        return "candidate_jobs_list"
    if "all jobs" in cleaned or "existing and new" in cleaned:
        return "all_accessible_jobs"
    return "new_to_candidate"


def extract_search_terms(message: str) -> list[str]:
    stop_words = {
        "a",
        "an",
        "and",
        "are",
        "find",
        "for",
        "give",
        "jobs",
        "job",
        "me",
        "new",
        "roles",
        "show",
        "some",
        "the",
        "to",
    }
    terms = []
    for token in re.findall(r"[A-Za-z][A-Za-z0-9+#.-]{1,}", message):
        cleaned = token.strip()
        if cleaned.casefold() not in stop_words and cleaned not in terms:
            terms.append(cleaned)
    return terms[:12]


def parse_db_search_plan(raw_text: str) -> DbJobSearchPlan:
    parsed = json.loads(extract_first_json(raw_text))
    plan = parsed.get("searchPlan", parsed)
    queries = tuple(parse_query(item) for item in plan.get("queries", [])) or (DbJobSearchQuery(),)
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
