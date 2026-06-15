from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy.orm import Session

from .company_canonicalization import ensure_candidate_company_link
from .company_sources.theirstack import TheirStackCompanyEnrichmentService, TheirStackCompanySearchRequest
from .company_sources.theirstack.client import TheirStackCompanySearchClient
from .company_sources.theirstack.service import build_candidate_company_metadata
from .db.models import CandidateCompany, CandidateProfile
from .model_connector import (
    ModelConfigurationError,
    ModelConnector,
    ModelMessage,
    ModelProviderError,
    ModelRequest,
    create_model_connector,
    read_model_connector_config_from_settings,
    route_model_request,
)
from .settings import Settings


MAX_THEIRSTACK_PLAN_LIMIT = 50
MAX_THEIRSTACK_PLAN_PAGES = 3
DEFAULT_THEIRSTACK_FRESHNESS_DAYS = 30


@dataclass(frozen=True)
class CompanyEnrichmentPlan:
    use_theirstack_company_search: bool
    rationale: str | None = None
    link_discovered_companies_to_profile: bool = True
    require_supported_ats: bool = False
    require_greenhouse: bool = False
    hiring_signal_terms: tuple[str, ...] = ()
    hiring_signal_source: str = "theirstack"
    requires_first_party_sync_for_verification: bool = True
    search: TheirStackCompanySearchRequest = field(default_factory=TheirStackCompanySearchRequest)
    clarifying_questions: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompanyEnrichmentServiceResult:
    handled: bool
    body: dict[str, Any]
    status_code: int


class EnrichmentPlanModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    use_theirstack_company_search: bool = Field(
        default=False,
        validation_alias=AliasChoices("use_theirstack_company_search", "useTheirStackCompanySearch"),
        serialization_alias="useTheirStackCompanySearch",
    )
    rationale: str | None = Field(default=None, max_length=900)
    link_discovered_companies_to_profile: bool = Field(
        default=True,
        validation_alias=AliasChoices("link_discovered_companies_to_profile", "linkDiscoveredCompaniesToProfile"),
        serialization_alias="linkDiscoveredCompaniesToProfile",
    )
    require_supported_ats: bool = Field(
        default=False,
        validation_alias=AliasChoices("require_supported_ats", "requireSupportedAts"),
        serialization_alias="requireSupportedAts",
    )
    require_greenhouse: bool = Field(
        default=False,
        validation_alias=AliasChoices("require_greenhouse", "requireGreenhouse"),
        serialization_alias="requireGreenhouse",
    )
    hiring_signal_terms: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("hiring_signal_terms", "hiringSignalTerms"),
        serialization_alias="hiringSignalTerms",
        max_length=24,
    )
    hiring_signal_source: str = Field(
        default="theirstack",
        validation_alias=AliasChoices("hiring_signal_source", "hiringSignalSource"),
        serialization_alias="hiringSignalSource",
        max_length=80,
    )
    requires_first_party_sync_for_verification: bool = Field(
        default=True,
        validation_alias=AliasChoices("requires_first_party_sync_for_verification", "requiresFirstPartySyncForVerification"),
        serialization_alias="requiresFirstPartySyncForVerification",
    )
    search: dict[str, Any] = Field(default_factory=dict)
    clarifying_questions: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("clarifying_questions", "clarifyingQuestions"),
        serialization_alias="clarifyingQuestions",
        max_length=5,
    )

    @field_validator("hiring_signal_terms", "clarifying_questions", mode="after")
    @classmethod
    def clean_string_list(cls, value: list[str]) -> list[str]:
        return compact_strings(value, limit=24)


def parse_company_enrichment_plan(raw_text: str, *, settings: Settings, context_text: str) -> tuple[CompanyEnrichmentPlan, list[dict[str, Any]]]:
    parsed = parse_json_object(raw_text)
    model = EnrichmentPlanModel.model_validate(parsed)
    return validate_company_enrichment_plan(model_to_plan(model), settings=settings, context_text=context_text)


def model_to_plan(model: EnrichmentPlanModel) -> CompanyEnrichmentPlan:
    search = parse_theirstack_search_request(model.search)
    return CompanyEnrichmentPlan(
        use_theirstack_company_search=model.use_theirstack_company_search,
        rationale=model.rationale,
        link_discovered_companies_to_profile=model.link_discovered_companies_to_profile,
        require_supported_ats=model.require_supported_ats,
        require_greenhouse=model.require_greenhouse,
        hiring_signal_terms=tuple(model.hiring_signal_terms),
        hiring_signal_source=model.hiring_signal_source or "theirstack",
        requires_first_party_sync_for_verification=model.requires_first_party_sync_for_verification,
        search=search,
        clarifying_questions=tuple(model.clarifying_questions),
    )


def parse_theirstack_search_request(raw: dict[str, Any]) -> TheirStackCompanySearchRequest:
    return TheirStackCompanySearchRequest(
        company_name_or=tuple_string_values(raw, "company_name_or", "companyNameOr"),
        company_name_partial_match_or=tuple_string_values(raw, "company_name_partial_match_or", "companyNamePartialMatchOr"),
        company_domain_or=tuple_string_values(raw, "company_domain_or", "companyDomainOr"),
        company_country_code_or=tuple_string_values(raw, "company_country_code_or", "companyCountryCodeOr"),
        company_description_pattern_or=tuple_string_values(raw, "company_description_pattern_or", "companyDescriptionPatternOr"),
        company_technology_slug_or=tuple_string_values(raw, "company_technology_slug_or", "companyTechnologySlugOr"),
        company_technology_slug_and=tuple_string_values(raw, "company_technology_slug_and", "companyTechnologySlugAnd"),
        company_keyword_slug_or=tuple_string_values(raw, "company_keyword_slug_or", "companyKeywordSlugOr"),
        job_filters=parse_job_filters(raw.get("job_filters") or raw.get("jobFilters")),
        limit=optional_int(raw.get("limit")),
        page=optional_int(raw.get("page")) or 1,
        max_pages=optional_int(raw.get("max_pages") or raw.get("maxPages")),
        include_total_results=bool(raw.get("include_total_results", raw.get("includeTotalResults", True))),
    )


def validate_company_enrichment_plan(
    plan: CompanyEnrichmentPlan,
    *,
    settings: Settings,
    context_text: str,
) -> tuple[CompanyEnrichmentPlan, list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    if not plan.use_theirstack_company_search:
        return plan, issues

    if not settings.theirstack_company_search_enabled or not settings.theirstack_api_key:
        return replace(
            plan,
            use_theirstack_company_search=False,
            clarifying_questions=(
                "TheirStack company enrichment is not configured yet, so I cannot use it for this request.",
            ),
        ), [{"code": "theirstack_unavailable", "message": "TheirStack is disabled or missing an API key."}]

    if is_jobs_list_or_direct_url_request(latest_message_from_context_text(context_text)):
        return replace(plan, use_theirstack_company_search=False), [
            {"code": "wrong_intent_for_theirstack", "message": "TheirStack enrichment is not used for saved-job ranking or direct job URLs."}
        ]

    clamped_search, clamp_issues = clamp_search_request(plan.search)
    issues.extend(clamp_issues)
    grounded_search, grounding_issues = remove_ungrounded_filters(clamped_search, context_text=context_text)
    issues.extend(grounding_issues)

    cleaned_terms = tuple(term for term in plan.hiring_signal_terms if term_is_grounded(term, context_text))
    removed_terms = [term for term in plan.hiring_signal_terms if term not in cleaned_terms]
    if removed_terms:
        issues.append({"code": "ungrounded_hiring_signal_terms_removed", "values": removed_terms})

    if not plan_has_meaningful_criteria(replace(plan, search=grounded_search, hiring_signal_terms=cleaned_terms)):
        return replace(
            plan,
            use_theirstack_company_search=False,
            search=grounded_search,
            hiring_signal_terms=cleaned_terms,
            clarifying_questions=(
                "What kind of companies, hiring signals, ATS metadata, role area, industry, or geography should I use?",
            ),
        ), [{"code": "missing_meaningful_company_enrichment_criteria", "message": "No meaningful TheirStack search criteria were planned."}]

    if plan.require_greenhouse and not plan_requests_greenhouse_evidence(grounded_search):
        issues.append(
            {
                "code": "greenhouse_required_without_explicit_filter",
                "message": "Greenhouse will be enforced after enrichment by requiring inferred board tokens.",
            }
        )

    return replace(plan, search=grounded_search, hiring_signal_terms=cleaned_terms), issues


class ModelPlannedCompanyEnrichmentService:
    def __init__(
        self,
        *,
        session: Session,
        settings: Settings,
        connector: ModelConnector | None = None,
        theirstack_client: TheirStackCompanySearchClient | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.connector = connector
        self.theirstack_client = theirstack_client

    def run(
        self,
        *,
        candidate_profile: CandidateProfile,
        latest_user_message: str,
        current_saved_companies: list[dict[str, Any]],
        target_context: dict[str, Any],
        profile_context: dict[str, Any],
        discovery_context: dict[str, Any],
    ) -> CompanyEnrichmentServiceResult:
        context = build_company_enrichment_context(
            latest_user_message=latest_user_message,
            current_saved_companies=current_saved_companies,
            target_context=target_context,
            profile_context=profile_context,
            discovery_context=discovery_context,
            settings=self.settings,
        )
        model_request = build_company_enrichment_plan_request(context)
        connector_config = read_model_connector_config_from_settings(self.settings)
        routed_request = route_model_request(model_request, connector_config.routing)
        try:
            active_connector = self.connector or create_model_connector(
                connector_config,
                mock_responses_by_task={"company_enrichment_planner": build_mock_company_enrichment_plan_response},
            )
        except ModelConfigurationError as error:
            return CompanyEnrichmentServiceResult(
                handled=False,
                status_code=503,
                body={
                    "ok": False,
                    "error": "Company enrichment planner model is not configured.",
                    "code": error.code,
                    "companyEnrichmentPlan": None,
                },
            )

        try:
            response = active_connector.generate(routed_request)
            plan, validation_issues = parse_company_enrichment_plan(
                response.text,
                settings=self.settings,
                context_text=json.dumps(context, sort_keys=True),
            )
        except (ModelProviderError, ValidationError, ValueError) as error:
            return CompanyEnrichmentServiceResult(
                handled=False,
                status_code=502,
                body={
                    "ok": False,
                    "error": "Company enrichment planner failed; falling back to standard company discovery.",
                    "code": getattr(error, "code", "company_enrichment_plan_failed"),
                    "companyEnrichmentPlan": None,
                },
            )

        if not plan.use_theirstack_company_search:
            if plan.clarifying_questions:
                return CompanyEnrichmentServiceResult(
                    handled=True,
                    status_code=200,
                    body={
                        "ok": True,
                        "result": build_clarifying_result_payload(plan, validation_issues, context),
                    },
                )
            return CompanyEnrichmentServiceResult(
                handled=False,
                status_code=200,
                body={"ok": True, "result": {"companyEnrichmentPlan": serialize_plan(plan), "validationIssues": validation_issues}},
            )

        enrichment = TheirStackCompanyEnrichmentService(
            session=self.session,
            settings=self.settings,
            client=self.theirstack_client,
        ).search_and_upsert_companies(
            plan.search,
            candidate_profile_id=candidate_profile.id,
            link_to_profile=plan.link_discovered_companies_to_profile and not plan.require_greenhouse,
            discovery_query=latest_user_message,
        )

        if plan.require_greenhouse:
            companies = link_greenhouse_required_companies(
                self.session,
                candidate_profile_id=candidate_profile.id,
                enrichment=enrichment,
                discovery_query=latest_user_message,
            )
        else:
            companies = [
                link
                for link in enrichment.candidate_company_links
                if isinstance(link, CandidateCompany) and link.company is not None
            ]

        result_payload = build_enrichment_result_payload(
            plan=plan,
            validation_issues=validation_issues,
            enrichment=enrichment,
            linked_companies=companies,
            latest_user_message=latest_user_message,
            context=context,
        )
        return CompanyEnrichmentServiceResult(
            handled=True,
            status_code=200 if enrichment.status in {"completed", "unavailable"} else 502,
            body={"ok": enrichment.status != "failed", "result": result_payload},
        )


def link_greenhouse_required_companies(
    session: Session,
    *,
    candidate_profile_id: str,
    enrichment: Any,
    discovery_query: str,
) -> list[CandidateCompany]:
    links: list[CandidateCompany] = []
    for company, normalized in zip(enrichment.companies, enrichment.normalized_companies, strict=False):
        if not getattr(company, "greenhouse_board_token", None):
            continue
        link_result = ensure_candidate_company_link(
            session,
            candidate_profile_id=candidate_profile_id,
            company=company,
            derivation_status="provider_enriched",
            discovery_query=discovery_query,
            search_queries_used=[discovery_query] if discovery_query else [],
            provider_grounding_metadata=build_candidate_company_metadata(
                normalized,
                discovery_query=discovery_query,
            ),
            discovered_by="theirstack",
            personal_source_urls=list(normalized.source_urls),
        )
        links.append(link_result.link)
    return links


def build_company_enrichment_context(
    *,
    latest_user_message: str,
    current_saved_companies: list[dict[str, Any]],
    target_context: dict[str, Any],
    profile_context: dict[str, Any],
    discovery_context: dict[str, Any],
    settings: Settings,
) -> dict[str, Any]:
    return {
        "latest_user_message": latest_user_message,
        "candidate_target_context": target_context,
        "candidate_profile_context": profile_context,
        "current_saved_companies": current_saved_companies,
        "company_discovery_context": discovery_context,
        "provider_capabilities": {
            "theirstack_enabled": settings.theirstack_company_search_enabled and bool(settings.theirstack_api_key),
            "theirstack_company_search_limit_default": settings.theirstack_company_search_limit,
            "theirstack_company_search_max_pages_default": settings.theirstack_company_search_max_pages,
            "theirstack_credit_note": "TheirStack may consume credits per returned company.",
            "can_infer_ats_metadata": ["greenhouse_board_token", "ashby_board_url", "lever_slug"],
            "not_canonical_job_detail_source": True,
            "requires_first_party_sync_for_verified_jobs": True,
        },
    }


def build_company_enrichment_plan_request(context: dict[str, Any]) -> ModelRequest:
    return ModelRequest(
        task="company_enrichment_planner",
        temperature=0,
        max_output_tokens=6000,
        response_mime_type="application/json",
        search_grounding=False,
        metadata={
            "feature": "company_enrichment_planner",
            "theirstack_enabled": context["provider_capabilities"]["theirstack_enabled"],
        },
        messages=[
            ModelMessage(role="system", content=COMPANY_ENRICHMENT_PLANNER_SYSTEM_PROMPT),
            ModelMessage(role="user", content=json.dumps(context, indent=2)),
        ],
    )


COMPANY_ENRICHMENT_PLANNER_SYSTEM_PROMPT = """You are the JobOps Company Enrichment Planner.

Return JSON only. Decide whether JobOps should use TheirStack company search for company discovery/enrichment.

Use TheirStack only when the user is asking to discover or enrich companies, company boards, ATS metadata, company hiring-signal leads, companies with Greenhouse boards, or companies TheirStack indicates are hiring for the user's target work.

Do not use TheirStack for ordinary saved-jobs ranking, direct job URL ingestion, or adding/saving a specific job URL. Do not use TheirStack for "look for jobs at my existing companies" when saved companies already have board metadata.

Provider capability context:
- TheirStack is available only when enabled and an API key is configured.
- TheirStack can search companies and expose hiring signals and URLs.
- TheirStack may consume credits per returned company, so keep requests narrow.
- TheirStack can help infer Greenhouse, Ashby, and Lever ATS metadata.
- TheirStack is not the canonical job-detail provider.
- First-party board sync is required before JobOps can verify actual current board jobs.

Planning rules:
- If the user explicitly asks for Greenhouse companies or companies with Greenhouse boards, set requireGreenhouse=true.
- If the user asks for companies "hiring for X", use TheirStack job_filters only when X is present in latest_user_message, candidate_target_context, candidate_profile_context, saved-company context, or recent discovery context.
- Preserve latest-message constraints.
- Use candidate target/profile context for role, industry, company-fit, technology, seniority, geography, and hiring-signal terms.
- Do not invent company names unless the user asked for companies like a known company from context.
- Do not invent role, domain, technology, geography, company, or job filters.
- Do not add hardcoded backend defaults for Applied AI, AI Engineer, LLM, software engineering, Greenhouse, healthcare, product marketing, or any other role/domain. Examples are examples only.
- If the request lacks enough company, role, industry, ATS, geography, or profile target context, ask a clarifying question or run broad ATS/company enrichment only when the latest message explicitly asks for broad company/ATS leads.

Return this JSON shape:
{
  "useTheirStackCompanySearch": true,
  "rationale": "Why TheirStack is or is not appropriate.",
  "linkDiscoveredCompaniesToProfile": true,
  "requireSupportedAts": false,
  "requireGreenhouse": false,
  "hiringSignalTerms": [],
  "hiringSignalSource": "theirstack",
  "requiresFirstPartySyncForVerification": true,
  "search": {
    "companyNameOr": [],
    "companyNamePartialMatchOr": [],
    "companyDomainOr": [],
    "companyCountryCodeOr": [],
    "companyDescriptionPatternOr": [],
    "companyTechnologySlugOr": [],
    "companyTechnologySlugAnd": [],
    "companyKeywordSlugOr": [],
    "jobFilters": {
      "job_title_pattern_or": [],
      "posted_at_max_age_days": 30
    },
    "limit": 25,
    "maxPages": 1
  },
  "clarifyingQuestions": []
}"""


def build_mock_company_enrichment_plan_response(request: ModelRequest) -> str:
    return json.dumps(
        {
            "useTheirStackCompanySearch": False,
            "rationale": "Mock planner leaves standard company discovery in charge.",
            "linkDiscoveredCompaniesToProfile": True,
            "requireSupportedAts": False,
            "requireGreenhouse": False,
            "hiringSignalTerms": [],
            "hiringSignalSource": "theirstack",
            "requiresFirstPartySyncForVerification": True,
            "search": {},
            "clarifyingQuestions": [],
        }
    )


def build_enrichment_result_payload(
    *,
    plan: CompanyEnrichmentPlan,
    validation_issues: list[dict[str, Any]],
    enrichment: Any,
    linked_companies: list[CandidateCompany],
    latest_user_message: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    companies_payload = [serialize_enriched_company(link) for link in linked_companies]
    greenhouse_count = sum(1 for link in linked_companies if link.company.greenhouse_board_token)
    ashby_count = sum(1 for link in linked_companies if link.company.ashby_board_url)
    lever_count = sum(1 for link in linked_companies if link.company.lever_slug)
    unsupported_count = sum(
        len(((link.provider_grounding_metadata or {}).get("atsInference") or {}).get("unsupportedAtsUrls") or [])
        for link in linked_companies
    )
    jobs_found_count = sum(
        int(((link.provider_grounding_metadata or {}).get("companyMetadata") or {}).get("numJobsFound") or 0)
        for link in linked_companies
    )
    filtered_no_greenhouse_count = (
        max(0, len(enrichment.companies) - len(linked_companies))
        if plan.require_greenhouse
        else 0
    )
    message = build_enrichment_assistant_message(
        linked_count=len(linked_companies),
        greenhouse_count=greenhouse_count,
        filtered_no_greenhouse_count=filtered_no_greenhouse_count,
        require_greenhouse=plan.require_greenhouse,
    )
    return {
        "assistantMessage": message,
        "companies": companies_payload,
        "enrichedCompanyCount": len(enrichment.companies),
        "rawCompanyCount": (enrichment.diagnostics or {}).get("rawCompanyCount"),
        "normalizedCompanyCount": (enrichment.diagnostics or {}).get("normalizedCompanyCount"),
        "upsertedCompanyCount": (enrichment.diagnostics or {}).get("upsertedCompanyCount"),
        "linkedCompanyCount": len(linked_companies),
        "filteredNoGreenhouseTokenCount": filtered_no_greenhouse_count,
        "greenhouseBoardTokenCount": greenhouse_count,
        "ashbyBoardUrlCount": ashby_count,
        "leverSlugCount": lever_count,
        "unsupportedAtsUrlCount": unsupported_count,
        "hiringSignalSource": plan.hiring_signal_source,
        "hiringSignalQuery": latest_user_message,
        "jobFiltersUsed": plan.search.job_filters,
        "jobsFoundCount": jobs_found_count,
        "exampleMatchingJobTitles": [],
        "requiresFirstPartySyncForVerification": plan.requires_first_party_sync_for_verification,
        "theirstackDiagnostics": enrichment.diagnostics,
        "companyEnrichmentPlan": serialize_plan(plan),
        "companyEnrichmentValidationIssues": validation_issues,
        "zeroResultReason": None if linked_companies else ("theirstackUnavailable" if enrichment.status == "unavailable" else "noTheirStackCompanyLeadsLinked"),
        "clarifyingQuestions": [],
        "sourceCaveat": "TheirStack returned hiring signals; JobOps has not synced first-party company boards for verification yet.",
    }


def build_clarifying_result_payload(
    plan: CompanyEnrichmentPlan,
    validation_issues: list[dict[str, Any]],
    context: dict[str, Any],
) -> dict[str, Any]:
    questions = list(plan.clarifying_questions) or ["What kind of companies should I enrich or discover?"]
    return {
        "assistantMessage": questions[0],
        "companies": [],
        "enrichedCompanyCount": 0,
        "linkedCompanyCount": 0,
        "greenhouseBoardTokenCount": 0,
        "ashbyBoardUrlCount": 0,
        "leverSlugCount": 0,
        "unsupportedAtsUrlCount": 0,
        "hiringSignalSource": plan.hiring_signal_source,
        "hiringSignalQuery": context.get("latest_user_message"),
        "jobFiltersUsed": {},
        "jobsFoundCount": 0,
        "exampleMatchingJobTitles": [],
        "requiresFirstPartySyncForVerification": True,
        "theirstackDiagnostics": {},
        "companyEnrichmentPlan": serialize_plan(plan),
        "companyEnrichmentValidationIssues": validation_issues,
        "zeroResultReason": "clarificationNeeded",
        "clarifyingQuestions": questions,
    }


def build_enrichment_assistant_message(
    *,
    linked_count: int,
    greenhouse_count: int,
    filtered_no_greenhouse_count: int,
    require_greenhouse: bool,
) -> str:
    if linked_count == 0:
        return (
            "I did not add company leads from TheirStack. TheirStack hiring signals are not verified JobOps board matches, "
            "and first-party board sync is still required before treating them as current openings."
        )
    company_word = "company lead" if linked_count == 1 else "company leads"
    if require_greenhouse:
        filtered_sentence = (
            f" I filtered out {filtered_no_greenhouse_count} TheirStack compan"
            f"{'y' if filtered_no_greenhouse_count == 1 else 'ies'} without Greenhouse board tokens."
            if filtered_no_greenhouse_count
            else ""
        )
        return (
            f"I added only companies with Greenhouse board tokens as leads: {linked_count} {company_word}. "
            f"{greenhouse_count} include Greenhouse board tokens.{filtered_sentence} "
            "I have not synced those boards yet, so these are leads for first-party verification."
        )
    return (
        f"I found {linked_count} {company_word} TheirStack returned for hiring signals related to your request. "
        f"{greenhouse_count} include Greenhouse board tokens. I have not synced those boards yet, so these are leads for first-party verification."
    )


def serialize_enriched_company(link: CandidateCompany) -> dict[str, Any]:
    company = link.company
    return {
        "id": link.id,
        "company_id": company.id,
        "name": company.name,
        "normalized_name": company.normalized_name,
        "website_url": company.website_url,
        "description": company.description,
        "greenhouse_board_token": company.greenhouse_board_token,
        "ashby_board_url": company.ashby_board_url,
        "lever_slug": company.lever_slug,
        "review_status": link.review_status,
        "derivation_status": link.derivation_status,
        "provider_grounding_metadata": link.provider_grounding_metadata,
    }


def serialize_plan(plan: CompanyEnrichmentPlan) -> dict[str, Any]:
    return {
        "useTheirStackCompanySearch": plan.use_theirstack_company_search,
        "rationale": plan.rationale,
        "linkDiscoveredCompaniesToProfile": plan.link_discovered_companies_to_profile,
        "requireSupportedAts": plan.require_supported_ats,
        "requireGreenhouse": plan.require_greenhouse,
        "hiringSignalTerms": list(plan.hiring_signal_terms),
        "hiringSignalSource": plan.hiring_signal_source,
        "requiresFirstPartySyncForVerification": plan.requires_first_party_sync_for_verification,
        "search": plan.search.to_api_body(),
        "clarifyingQuestions": list(plan.clarifying_questions),
    }


def parse_json_object(raw_text: str) -> dict[str, Any]:
    stripped = raw_text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            stripped = "\n".join(lines[1:-1]).strip()
    parsed = json.loads(stripped)
    if not isinstance(parsed, dict):
        raise ValueError("Company enrichment plan must be a JSON object.")
    return parsed


def tuple_string_values(raw: dict[str, Any], *keys: str) -> tuple[str, ...]:
    value = next((raw.get(key) for key in keys if key in raw), None)
    if not isinstance(value, list):
        return ()
    return tuple(compact_strings(value, limit=24))


def parse_job_filters(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    allowed: dict[str, Any] = {}
    for key, raw in value.items():
        if key in {"job_title_pattern_or", "job_title_pattern_and", "job_country_code_or", "posted_at_max_age_days"}:
            if isinstance(raw, list):
                allowed[key] = compact_strings(raw, limit=24)
            elif isinstance(raw, (str, int, float)):
                allowed[key] = raw
    return allowed


def clamp_search_request(search: TheirStackCompanySearchRequest) -> tuple[TheirStackCompanySearchRequest, list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    limit = search.limit
    if limit is not None and limit > MAX_THEIRSTACK_PLAN_LIMIT:
        issues.append({"code": "theirstack_limit_clamped", "from": limit, "to": MAX_THEIRSTACK_PLAN_LIMIT})
        limit = MAX_THEIRSTACK_PLAN_LIMIT
    max_pages = search.max_pages
    if max_pages is not None and max_pages > MAX_THEIRSTACK_PLAN_PAGES:
        issues.append({"code": "theirstack_max_pages_clamped", "from": max_pages, "to": MAX_THEIRSTACK_PLAN_PAGES})
        max_pages = MAX_THEIRSTACK_PLAN_PAGES
    return replace(search, limit=limit, max_pages=max_pages), issues


def remove_ungrounded_filters(search: TheirStackCompanySearchRequest, *, context_text: str) -> tuple[TheirStackCompanySearchRequest, list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []

    def grounded(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
        kept = tuple(value for value in values if term_is_grounded(value, context_text))
        removed = [value for value in values if value not in kept]
        if removed:
            issues.append({"code": "ungrounded_filter_removed", "field": field_name, "values": removed})
        return kept

    job_filters = dict(search.job_filters)
    for key in ("job_title_pattern_or", "job_title_pattern_and"):
        value = job_filters.get(key)
        if isinstance(value, list):
            kept = [item for item in value if term_is_grounded(str(item), context_text)]
            removed = [item for item in value if item not in kept]
            if removed:
                issues.append({"code": "ungrounded_filter_removed", "field": key, "values": removed})
            if kept:
                job_filters[key] = kept
            else:
                job_filters.pop(key, None)

    return replace(
        search,
        company_name_or=grounded(search.company_name_or, "company_name_or"),
        company_name_partial_match_or=grounded(search.company_name_partial_match_or, "company_name_partial_match_or"),
        company_description_pattern_or=grounded(search.company_description_pattern_or, "company_description_pattern_or"),
        company_technology_slug_or=grounded(search.company_technology_slug_or, "company_technology_slug_or"),
        company_technology_slug_and=grounded(search.company_technology_slug_and, "company_technology_slug_and"),
        company_keyword_slug_or=grounded(search.company_keyword_slug_or, "company_keyword_slug_or"),
        job_filters=job_filters,
    ), issues


def term_is_grounded(term: str, context_text: str) -> bool:
    normalized_term = normalize_for_match(term)
    if not normalized_term:
        return False
    normalized_context = normalize_for_match(context_text)
    return normalized_term in normalized_context or all(part in normalized_context for part in normalized_term.split())


def plan_has_meaningful_criteria(plan: CompanyEnrichmentPlan) -> bool:
    if plan.require_greenhouse or plan.require_supported_ats:
        return True
    search = plan.search
    return any(
        [
            search.company_name_or,
            search.company_name_partial_match_or,
            search.company_domain_or,
            search.company_country_code_or,
            search.company_description_pattern_or,
            search.company_technology_slug_or,
            search.company_technology_slug_and,
            search.company_keyword_slug_or,
            search.job_filters,
            plan.hiring_signal_terms,
        ]
    )


def plan_requests_greenhouse_evidence(search: TheirStackCompanySearchRequest) -> bool:
    text = json.dumps(search.to_api_body(), sort_keys=True).casefold()
    return "greenhouse" in text


def is_jobs_list_or_direct_url_request(context_text: str) -> bool:
    normalized = normalize_for_match(context_text)
    return "http" in normalized or "which jobs" in normalized or "what jobs" in normalized or "apply to today" in normalized


def latest_message_from_context_text(context_text: str) -> str:
    try:
        parsed = json.loads(context_text)
    except json.JSONDecodeError:
        return context_text
    if isinstance(parsed, dict) and isinstance(parsed.get("latest_user_message"), str):
        return parsed["latest_user_message"]
    return context_text


def optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def compact_strings(values: list[Any] | tuple[Any, ...], *, limit: int) -> list[str]:
    compacted: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        cleaned = " ".join(value.split())[:160]
        key = cleaned.casefold()
        if cleaned and key not in seen:
            compacted.append(cleaned)
            seen.add(key)
        if len(compacted) >= limit:
            break
    return compacted


def normalize_for_match(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9+#.-]+", value.casefold()))
