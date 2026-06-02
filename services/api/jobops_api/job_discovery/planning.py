from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from ..company_discovery import (
    add_truncation_hint,
    extract_first_json_object,
    format_validation_issues,
    model_request_debug_fields,
    model_response_debug_fields,
    safe_error_detail_fields,
    validation_issues_indicate_truncation,
)
from ..model_connector import (
    ModelConfigurationError,
    ModelConnector,
    ModelMessage,
    ModelProviderError,
    ModelRequest,
    create_model_connector,
    read_model_connector_config_from_settings,
    route_model_request,
)
from ..settings import Settings
from .models import (
    JobDiscoveryRequest,
    JobSearchPlan,
    JobSearchPlanProviderStrategy,
    JobSearchPlannerOutput,
    JobSearchPlannerResult,
)
from .provider_utils import clean_text_value, compact_unique_strings, extract_location_from_command, normalize_exclusion_terms


class JobSearchPlanningValidationFailure(Exception):
    def __init__(self, issues: list[str]) -> None:
        super().__init__("Job search planner output validation failed.")
        self.issues = issues


def select_job_search_plan_with_model(
    request: JobDiscoveryRequest,
    *,
    connector: ModelConnector | None,
    settings: Settings,
    router_extracted: dict[str, Any] | None,
    current_saved_jobs: list[dict[str, Any]],
    current_saved_companies: list[dict[str, Any]],
    target_context: dict[str, Any],
    private_profile_context: dict[str, Any],
    recent_search_history: list[dict[str, Any]],
    provider_capabilities: dict[str, Any],
    replan_context: dict[str, Any] | None = None,
) -> JobSearchPlannerResult:
    model_request = build_job_search_planner_model_request(
        request,
        router_extracted=router_extracted,
        current_saved_jobs=current_saved_jobs,
        current_saved_companies=current_saved_companies,
        target_context=target_context,
        private_profile_context=private_profile_context,
        recent_search_history=recent_search_history,
        provider_capabilities=provider_capabilities,
        replan_context=replan_context,
    )
    connector_config = read_model_connector_config_from_settings(settings)
    routed_request = route_model_request(model_request, connector_config.routing)
    fallback_plan = build_fallback_job_search_plan(
        request,
        router_extracted=router_extracted,
        current_saved_companies=current_saved_companies,
        target_context=target_context,
        private_profile_context=private_profile_context,
        settings=settings,
    )
    try:
        active_connector = connector or create_model_connector(
            connector_config,
            mock_responses_by_task={"job_search_planning": build_mock_job_search_planner_response},
        )
        response = active_connector.generate(routed_request)
        output = validate_job_search_planner_output(response.text)
        return JobSearchPlannerResult(
            plan=apply_job_search_plan_guardrails(
                output.search_plan,
                request=request,
                router_extracted=router_extracted,
                current_saved_companies=current_saved_companies,
                fallback_plan=fallback_plan,
                settings=settings,
            ),
            request=routed_request,
            response_provider=response.provider,
            response_model=response.model,
            response=response,
            fallback_used=False,
            recent_searches_used_count=len(recent_search_history),
        )
    except Exception as error:
        return JobSearchPlannerResult(
            plan=fallback_plan,
            request=routed_request,
            response_provider="fallback",
            response_model="deterministic",
            response={
                "error": type(error).__name__,
                "validationIssues": getattr(error, "issues", None),
                **(safe_error_detail_fields(settings, error) if isinstance(error, ModelConfigurationError) else {}),
                **model_request_debug_fields(settings, routed_request),
            },
            fallback_used=True,
            recent_searches_used_count=len(recent_search_history),
        )


def build_job_search_planner_model_request(
    request: JobDiscoveryRequest,
    *,
    router_extracted: dict[str, Any] | None,
    current_saved_jobs: list[dict[str, Any]],
    current_saved_companies: list[dict[str, Any]],
    target_context: dict[str, Any],
    private_profile_context: dict[str, Any],
    recent_search_history: list[dict[str, Any]],
    provider_capabilities: dict[str, Any],
    replan_context: dict[str, Any] | None = None,
) -> ModelRequest:
    payload = {
        "latest_user_message": request.latest_user_message,
        "active_workspace": request.active_workspace,
        "router_extracted_fields": router_extracted or {},
        "candidate_target_context": target_context,
        "private_profile_context": private_profile_context,
        "current_saved_companies": current_saved_companies[:50],
        "current_saved_jobs_summary": compact_saved_jobs_for_planner(current_saved_jobs),
        "recent_job_search_history": recent_search_history[:50],
        "provider_capabilities": provider_capabilities,
        "replan_context": replan_context or {},
        "planning_rules": {
            "latest_user_message_is_highest_priority": True,
            "do_not_invent_saved_companies_or_job_facts": True,
            "provider_backed_search_only": True,
            "output_structured_json_only": True,
        },
    }
    return ModelRequest(
        task="job_search_planning",
        temperature=0.1,
        max_output_tokens=5000,
        response_mime_type="application/json",
        search_grounding=False,
        metadata={
            "feature": "job_search_planning",
            "saved_company_count": len(current_saved_companies),
            "recent_search_count": len(recent_search_history),
        },
        messages=[
            ModelMessage(role="system", content=JOB_SEARCH_PLANNER_SYSTEM_PROMPT),
            ModelMessage(role="user", content=json.dumps(payload, sort_keys=True, default=str)),
        ],
    )


JOB_SEARCH_PLANNER_SYSTEM_PROMPT = """You are the JobOps Job Search Planning Agent.

Create a provider-backed search plan from the latest Command Center message plus authenticated profile, saved-company, saved-job, and recent-search context.

Rules:
- Return JSON only.
- Do not invent job facts, companies, saved jobs, or previous searches.
- Preserve explicit user constraints, including company, location, work mode, salary, employment type, and exclusions.
- Treat the latest user message as the highest-priority signal.
- Use profile targets and private profile context only when the latest command is vague.
- Use recent search history to avoid repeating ineffective zero-result searches unless the user explicitly asks to check again.
- For company-specific requests, include only the explicit/saved company names.
- For "my companies list" or "companies I follow", use followed_companies mode.
- Return provider-appropriate role queries, not generic "jobs", unless the user explicitly asks for a broad exploratory search and no better context exists.
- Do not use web search or browsing.

Return exactly this JSON shape:
{
  "searchPlan": {
    "searchMode": "broad",
    "roleQueries": ["Applied AI Engineer"],
    "companyNames": [],
    "locations": ["Remote US"],
    "remoteWorkModes": ["remote"],
    "employmentTypes": ["Full-time"],
    "salaryMin": 130000,
    "includeTerms": ["LLM"],
    "excludeTerms": ["manager"],
    "hardConstraints": ["remote"],
    "softPreferences": ["mission-driven"],
    "providerStrategy": {
      "useBroadSearch": true,
      "useCompanyBoards": true,
      "requestedResultGoal": 50,
      "maxProviderPages": 2,
      "allowReplanning": true
    },
    "rationale": "Short explanation."
  }
}"""


def validate_job_search_planner_output(raw_text: str) -> JobSearchPlannerOutput:
    try:
        parsed = parse_planner_json(raw_text)
        return JobSearchPlannerOutput.model_validate(parsed)
    except (json.JSONDecodeError, ValueError, ValidationError) as error:
        issues = [str(error)]
        if isinstance(error, ValidationError):
            issues = format_validation_issues(error)
        raise JobSearchPlanningValidationFailure(issues) from error


def parse_planner_json(raw_text: str) -> Any:
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        extracted = extract_first_json_object(raw_text)
        if extracted is None:
            raise
        return json.loads(extracted)


def apply_job_search_plan_guardrails(
    plan: JobSearchPlan,
    *,
    request: JobDiscoveryRequest,
    router_extracted: dict[str, Any] | None,
    current_saved_companies: list[dict[str, Any]],
    fallback_plan: JobSearchPlan,
    settings: Settings,
) -> JobSearchPlan:
    company_names = plan.company_names
    explicit_company = clean_text_value((router_extracted or {}).get("companyName") or (router_extracted or {}).get("company_name"))
    if explicit_company:
        company_names = [explicit_company]
    elif plan.search_mode == "followed_companies":
        company_names = [str(company.get("name")) for company in current_saved_companies if company.get("name")]
    elif plan.search_mode == "company_specific":
        saved_names = {str(company.get("name") or "").casefold(): str(company.get("name")) for company in current_saved_companies}
        company_names = [saved_names.get(name.casefold(), name) for name in company_names]

    role_queries = [query for query in plan.role_queries if not is_generic_junk_query(query)]
    if not role_queries:
        role_queries = fallback_plan.role_queries
    if not role_queries:
        role_queries = ["jobs"]

    max_pages = max(1, min(plan.provider_strategy.max_provider_pages, settings.job_discovery_max_provider_pages, 5))
    requested_result_goal = max(
        plan.provider_strategy.requested_result_goal,
        min(settings.job_discovery_results_per_provider, max(settings.job_discovery_save_limit * 2, settings.job_discovery_save_limit)),
    )
    strategy = plan.provider_strategy.model_copy(
        update={
            "requested_result_goal": max(1, min(requested_result_goal, settings.job_discovery_results_per_provider)),
            "max_provider_pages": max_pages,
            "allow_replanning": plan.provider_strategy.allow_replanning and settings.job_discovery_search_replan_limit > 0,
        }
    )
    return JobSearchPlan(
        searchMode=plan.search_mode,
        roleQueries=compact_unique_strings(role_queries, limit=8),
        companyNames=compact_unique_strings(company_names, limit=settings.job_discovery_company_search_limit),
        locations=compact_unique_strings(plan.locations or fallback_plan.locations, limit=8),
        remoteWorkModes=compact_unique_strings(plan.remote_work_modes or fallback_plan.remote_work_modes, limit=5),
        employmentTypes=compact_unique_strings(plan.employment_types, limit=8),
        salaryMin=plan.salary_min,
        includeTerms=compact_unique_strings(plan.include_terms, limit=12),
        excludeTerms=compact_unique_strings([*plan.exclude_terms, *fallback_plan.exclude_terms], limit=20),
        hardConstraints=compact_unique_strings(plan.hard_constraints, limit=12),
        softPreferences=compact_unique_strings(plan.soft_preferences, limit=12),
        providerStrategy=strategy,
        rationale=plan.rationale or fallback_plan.rationale,
    )


def build_fallback_job_search_plan(
    request: JobDiscoveryRequest,
    *,
    router_extracted: dict[str, Any] | None,
    current_saved_companies: list[dict[str, Any]],
    target_context: dict[str, Any],
    private_profile_context: dict[str, Any],
    settings: Settings,
) -> JobSearchPlan:
    message = request.latest_user_message
    normalized = " ".join(message.casefold().split())
    role_queries = infer_fallback_role_queries(message, target_context, private_profile_context)
    company_names: list[str] = []
    explicit_company = clean_text_value((router_extracted or {}).get("companyName") or (router_extracted or {}).get("company_name"))
    search_mode = "broad"
    if explicit_company:
        company_names = [explicit_company]
        search_mode = "company_specific"
    elif mentions_followed_companies(normalized):
        company_names = [str(company.get("name")) for company in current_saved_companies if company.get("name")]
        search_mode = "followed_companies"
    else:
        inferred_company = infer_company_name_from_job_search_message(message)
        if inferred_company:
            company_names = [inferred_company]
            search_mode = "company_specific"

    remote_modes = infer_remote_modes(normalized)
    locations = infer_locations(message)
    return JobSearchPlan(
        searchMode=search_mode,
        roleQueries=role_queries,
        companyNames=compact_unique_strings(company_names, limit=settings.job_discovery_company_search_limit),
        locations=locations,
        remoteWorkModes=remote_modes,
        employmentTypes=infer_employment_types(normalized),
        salaryMin=infer_salary_min(normalized),
        includeTerms=[],
        excludeTerms=extract_exclusions(normalized),
        hardConstraints=[*locations, *remote_modes],
        softPreferences=[],
        providerStrategy=JobSearchPlanProviderStrategy(
            useBroadSearch=True,
            useCompanyBoards=True,
            requestedResultGoal=settings.job_discovery_results_per_provider,
            maxProviderPages=settings.job_discovery_max_provider_pages,
            allowReplanning=settings.job_discovery_search_replan_limit > 0,
        ),
        rationale="Deterministic fallback search plan derived from the latest command and saved profile context.",
    )


def infer_fallback_role_queries(message: str, target_context: dict[str, Any], private_profile_context: dict[str, Any]) -> list[str]:
    queries: list[str] = []
    explicit_location = extract_location_from_command(message)
    cleaned_message = message
    if explicit_location:
        cleaned_message = re.sub(
            rf"\b(?:in|near|around|within|based\s+in|located\s+in)\s+{re.escape(explicit_location)}\b",
            " ",
            cleaned_message,
            flags=re.IGNORECASE,
        )
    cleaned_message = re.sub(r"\b(find|search|look|check|for|new|again|jobs?|roles?|postings?|openings?|at|from|my|companies|list|following|followed|in)\b", " ", cleaned_message, flags=re.IGNORECASE)
    cleaned_message = re.sub(r"\b(remote|hybrid|onsite|on-site|louisville|over|above|at least|\$?\d+k?)\b", " ", cleaned_message, flags=re.IGNORECASE)
    cleaned_message = re.sub(r"\b(not|no|without|avoid)\b.+", " ", cleaned_message, flags=re.IGNORECASE)
    candidate = " ".join(cleaned_message.split()).strip(" ,.;:-")
    if candidate and len(candidate) <= 80 and not re.search(r"\b(companies|tomoro|again|broader)\b", candidate, re.IGNORECASE):
        queries.append(title_case_query(candidate))
    queries.extend(str(item) for item in target_context.get("target_role_titles") or [] if item)
    queries.extend(str(item) for item in target_context.get("target_role_families") or [] if item)
    basics = private_profile_context.get("profile_basics") if isinstance(private_profile_context, dict) else {}
    headline = clean_text_value((basics or {}).get("headline"))
    if headline and "setup in progress" not in headline.casefold():
        queries.append(headline.split("|", 1)[0].strip())
    if not queries:
        queries.append("jobs")
    return compact_unique_strings(queries, limit=6)


def build_mock_job_search_planner_response(request: ModelRequest) -> str:
    payload = json.loads(request.messages[-1].content) if request.messages else {}
    context = payload if isinstance(payload, dict) else {}
    latest = str(context.get("latest_user_message") or "")
    plan = build_fallback_job_search_plan(
        JobDiscoveryRequest(
            latest_user_message=latest,
            candidate_profile_slug="mock",
            active_workspace=context.get("active_workspace") if isinstance(context.get("active_workspace"), str) else None,
        ),
        router_extracted=context.get("router_extracted_fields") if isinstance(context.get("router_extracted_fields"), dict) else {},
        current_saved_companies=context.get("current_saved_companies") if isinstance(context.get("current_saved_companies"), list) else [],
        target_context=context.get("candidate_target_context") if isinstance(context.get("candidate_target_context"), dict) else {},
        private_profile_context=context.get("private_profile_context") if isinstance(context.get("private_profile_context"), dict) else {},
        settings=mock_settings_from_provider_capabilities(context.get("provider_capabilities")),
    )
    return json.dumps({"searchPlan": plan.model_dump(by_alias=True)})


def mock_settings_from_provider_capabilities(capabilities: object) -> Settings:
    from pathlib import Path

    limits = capabilities.get("limits") if isinstance(capabilities, dict) else {}
    return Settings(
        app_env="test",
        model_provider="mock",
        default_model="mock-default",
        cheap_model="mock-cheap",
        gemini_api_key=None,
        profile_intake_save_artifacts=False,
        profile_intake_save_raw_text=False,
        company_discovery_search_grounding_enabled=True,
        database_url=None,
        repo_root=Path.cwd(),
        job_discovery_results_per_provider=int((limits or {}).get("results_per_provider") or 20),
        job_discovery_max_provider_pages=int((limits or {}).get("max_provider_pages") or 2),
        job_discovery_search_replan_limit=int((limits or {}).get("replan_limit") or 1),
    )


def compact_saved_jobs_for_planner(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "title": job.get("title"),
            "company_name": job.get("company_name"),
            "normalized_url": job.get("normalized_url"),
            "status": job.get("status"),
            "added_at": job.get("added_at"),
        }
        for job in jobs[:50]
    ]


def is_generic_junk_query(value: str) -> bool:
    normalized = " ".join(value.casefold().split())
    return normalized in {"", "job", "jobs", "find jobs", "search jobs", "new jobs", "relevant jobs"}


def mentions_followed_companies(normalized: str) -> bool:
    return any(signal in normalized for signal in ["my companies list", "companies i follow", "companies i'm following", "saved companies", "followed companies"])


def infer_company_name_from_job_search_message(message: str) -> str | None:
    patterns = [
        r"\b(?:at|from|for)\s+([A-Z][A-Za-z0-9&.\- ]{1,60}?)(?:\s+(?:again|jobs?|roles?|openings?|but|remote|hybrid)|[.?!]|$)",
        r"\bcheck\s+([A-Z][A-Za-z0-9&.\- ]{1,60}?)(?:\s+again|[.?!]|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, message)
        if match:
            value = " ".join(match.group(1).split()).strip(" ,.;:-")
            if value and value.casefold() not in {"my companies list", "companies i follow"}:
                return value
    return None


def infer_remote_modes(normalized: str) -> list[str]:
    modes: list[str] = []
    if "remote" in normalized:
        modes.append("remote")
    if "hybrid" in normalized:
        modes.append("hybrid")
    if "onsite" in normalized or "on-site" in normalized:
        modes.append("onsite")
    return modes


def infer_locations(message: str) -> list[str]:
    locations: list[str] = []
    command_location = extract_location_from_command(message)
    if command_location:
        locations.append(command_location)
    if re.search(r"\blouisville\b", message, re.IGNORECASE):
        locations.append("Louisville")
    if re.search(r"\bremote\s+us\b", message, re.IGNORECASE):
        locations.append("Remote US")
    return locations


def infer_salary_min(normalized: str) -> int | None:
    match = re.search(r"\b(?:over|above|at least)\s+\$?(\d{2,3})(?:k|,000)?\b", normalized)
    if not match:
        return None
    amount = int(match.group(1))
    return amount * 1000 if amount < 1000 else amount


def infer_employment_types(normalized: str) -> list[str]:
    values: list[str] = []
    for label, signals in {
        "Full-time": ["full-time", "full time"],
        "Contract": ["contract"],
        "Part-time": ["part-time", "part time"],
        "Internship": ["internship", "intern"],
        "Temporary": ["temporary", "temp"],
    }.items():
        if any(signal in normalized for signal in signals):
            values.append(label)
    return values


def extract_exclusions(normalized: str) -> list[str]:
    terms: list[str] = []
    for match in re.finditer(r"\b(?:avoid|exclude|without|not|no|don't include|dont include)\b([^.!?\n]+)", normalized):
        terms.extend(normalize_exclusion_terms(match.group(1)))
    return compact_unique_strings(terms, limit=20)


def title_case_query(value: str) -> str:
    return " ".join(word.upper() if word.isupper() else word.capitalize() for word in value.split())
