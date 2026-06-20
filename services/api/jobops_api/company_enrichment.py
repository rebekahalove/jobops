from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .company_canonicalization import ensure_candidate_company_link
from .company_discovery_diagnostics import (
    complete_company_discovery_run,
    record_company_discovery_provider_call,
    update_company_discovery_provider_call,
    update_company_discovery_run,
)
from .company_sources.theirstack import TheirStackCompanyEnrichmentService, TheirStackCompanySearchRequest
from .company_sources.theirstack.client import TheirStackCompanySearchClient
from .company_sources.theirstack.service import build_candidate_company_metadata
from .db.models import CandidateCompany, CandidateProfile, JobListingSource, JobSearchQueryRun, JobSearchRun
from .job_discovery.ashby_utils import parse_ashby_job_board_url
from .job_discovery.candidate_discovery.models import DbJobSearchPlan, DbJobSearchQuery, JobPoolEntry
from .job_discovery.candidate_discovery.query_builder import JobListingQueryBuilder, job_listing_to_pool_entry
from .job_discovery.candidate_discovery.repositories import CandidateJobRepository, rejection_reason_counts
from .job_discovery.candidate_discovery.reviewer import JobReviewSelector, validate_review_result
from .job_discovery.job_sync.ashby_service import sync_ashby_boards
from .job_discovery.job_sync.greenhouse_service import sync_greenhouse_boards
from .job_discovery.models import JobDiscoveryRequest
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


logger = logging.getLogger(__name__)
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
    sync_discovered_ats_boards: bool = False
    sync_discovered_greenhouse_boards: bool = False
    sync_discovered_ashby_boards: bool = False
    search_synced_jobs_after_board_sync: bool = False
    save_matching_jobs_to_candidate_list: bool = False
    recommend_only: bool = False
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
    sync_discovered_ats_boards: bool = Field(
        default=False,
        validation_alias=AliasChoices("sync_discovered_ats_boards", "syncDiscoveredAtsBoards", "syncDiscoveredCompanyBoards"),
        serialization_alias="syncDiscoveredAtsBoards",
    )
    sync_discovered_greenhouse_boards: bool = Field(
        default=False,
        validation_alias=AliasChoices("sync_discovered_greenhouse_boards", "syncDiscoveredGreenhouseBoards"),
        serialization_alias="syncDiscoveredGreenhouseBoards",
    )
    sync_discovered_ashby_boards: bool = Field(
        default=False,
        validation_alias=AliasChoices("sync_discovered_ashby_boards", "syncDiscoveredAshbyBoards"),
        serialization_alias="syncDiscoveredAshbyBoards",
    )
    search_synced_jobs_after_board_sync: bool = Field(
        default=False,
        validation_alias=AliasChoices("search_synced_jobs_after_board_sync", "searchSyncedJobsAfterBoardSync"),
        serialization_alias="searchSyncedJobsAfterBoardSync",
    )
    save_matching_jobs_to_candidate_list: bool = Field(
        default=False,
        validation_alias=AliasChoices("save_matching_jobs_to_candidate_list", "saveMatchingJobsToCandidateList"),
        serialization_alias="saveMatchingJobsToCandidateList",
    )
    recommend_only: bool = Field(
        default=False,
        validation_alias=AliasChoices("recommend_only", "recommendOnly"),
        serialization_alias="recommendOnly",
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
        sync_discovered_ats_boards=model.sync_discovered_ats_boards,
        sync_discovered_greenhouse_boards=model.sync_discovered_greenhouse_boards,
        sync_discovered_ashby_boards=model.sync_discovered_ashby_boards,
        search_synced_jobs_after_board_sync=model.search_synced_jobs_after_board_sync,
        save_matching_jobs_to_candidate_list=model.save_matching_jobs_to_candidate_list,
        recommend_only=model.recommend_only,
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

    if plan.search_synced_jobs_after_board_sync and not plan_requests_any_board_sync(plan):
        issues.append(
            {
                "code": "post_enrichment_search_requires_board_sync",
                "message": "Searching post-enrichment jobs requires first-party board sync first.",
            }
        )
        plan = replace(plan, search_synced_jobs_after_board_sync=False, save_matching_jobs_to_candidate_list=False)
    if plan.recommend_only and plan.save_matching_jobs_to_candidate_list:
        issues.append(
            {
                "code": "recommend_only_disables_saving_jobs",
                "message": "recommendOnly prevents saving selected jobs to the jobs list.",
            }
        )
        plan = replace(plan, save_matching_jobs_to_candidate_list=False)

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
        company_discovery_run_id: str | None = None,
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
        record_company_discovery_provider_call(
            self.session,
            company_discovery_run_id=company_discovery_run_id,
            stage="planner",
            provider=response.provider or connector_config.provider or "model",
            status="completed",
            label="Company enrichment planner",
            request_summary={
                "theirstackEnabled": bool(self.settings.theirstack_company_search_enabled and self.settings.theirstack_api_key),
                "canInferAtsMetadata": True,
            },
            result_summary={
                "useTheirStackCompanySearch": plan.use_theirstack_company_search,
                "requireSupportedAts": plan.require_supported_ats,
                "requireGreenhouse": plan.require_greenhouse,
                "syncDiscoveredAtsBoards": plan.sync_discovered_ats_boards,
                "syncDiscoveredGreenhouseBoards": plan.sync_discovered_greenhouse_boards,
                "syncDiscoveredAshbyBoards": plan.sync_discovered_ashby_boards,
                "searchSyncedJobsAfterBoardSync": plan.search_synced_jobs_after_board_sync,
                "validationIssueCodes": [issue.get("code") for issue in validation_issues if isinstance(issue.get("code"), str)],
            },
        )

        if not plan.use_theirstack_company_search:
            if any(issue.get("code") == "theirstack_unavailable" for issue in validation_issues):
                record_company_discovery_provider_call(
                    self.session,
                    company_discovery_run_id=company_discovery_run_id,
                    stage="company_source",
                    provider="theirstack",
                    status="unavailable",
                    label="TheirStack company search",
                    request_summary={
                        "requestShape": sanitized_company_diagnostic_request_shape(plan.search.sanitized_shape()),
                        "requestedPages": plan.search.max_pages,
                        "limit": plan.search.limit,
                    },
                    result_summary={"skippedReason": "missing_api_key"},
                    error={"message": "TheirStack is disabled or missing an API key."},
                )
            logger.info(
                "company_enrichment.planner_decision",
                extra={
                    "candidate_profile_id": candidate_profile.id,
                    "command_preview": compact_log_preview(latest_user_message),
                    "theirstack_checked": True,
                    "theirstack_enabled": bool(self.settings.theirstack_company_search_enabled and self.settings.theirstack_api_key),
                    "theirstack_used": False,
                    "skipped_reason": "clarification_needed" if plan.clarifying_questions else "planner_chose_model_grounded",
                    "validation_issue_count": len(validation_issues),
                },
            )
            if plan.clarifying_questions:
                complete_company_discovery_run(
                    self.session,
                    company_discovery_run_id,
                    status="needs_confirmation",
                    source_path="clarification",
                    source_provider="theirstack",
                    model_provider=response.provider,
                    model_name=response.model,
                    zero_new_company_reason="clarificationNeeded",
                    run_diagnostics_json={
                        "theirStack": {"checked": True, "enabled": bool(self.settings.theirstack_company_search_enabled and self.settings.theirstack_api_key), "used": False},
                        "firstPartySync": {},
                        "companies": [],
                        "diagnosticMessages": [],
                    },
                )
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

        update_company_discovery_run(
            self.session,
            company_discovery_run_id,
            source_path="theirstack_company_enrichment",
            source_provider="theirstack",
            model_provider=response.provider,
            model_name=response.model,
        )
        theirstack_call = record_company_discovery_provider_call(
            self.session,
            company_discovery_run_id=company_discovery_run_id,
            stage="company_source",
            provider="theirstack",
            status="started",
            label="TheirStack company search",
            request_summary={
                "requestShape": sanitized_company_diagnostic_request_shape(plan.search.sanitized_shape()),
                "requestedPages": plan.search.max_pages,
                "limit": plan.search.limit,
                "creditsAwareness": "TheirStack may consume credits per returned company.",
            },
        )
        logger.info(
            "theirstack.company_search.started",
            extra={
                "candidate_profile_id": candidate_profile.id,
                "command_preview": compact_log_preview(latest_user_message),
                "source_path": "theirstack_company_enrichment",
                "theirstack_checked": True,
                "theirstack_enabled": True,
                "theirstack_used": True,
                "request_shape": sanitized_company_diagnostic_request_shape(plan.search.sanitized_shape()),
            },
        )
        enrichment = TheirStackCompanyEnrichmentService(
            session=self.session,
            settings=self.settings,
            client=self.theirstack_client,
        ).search_and_upsert_companies(
            plan.search,
            candidate_profile_id=candidate_profile.id,
            link_to_profile=plan.link_discovered_companies_to_profile
            and not plan.require_greenhouse
            and not plan.require_supported_ats,
            discovery_query=latest_user_message,
        )
        diagnostics = enrichment.diagnostics if isinstance(enrichment.diagnostics, dict) else {}
        update_company_discovery_provider_call(
            self.session,
            theirstack_call,
            status="unavailable" if enrichment.status == "unavailable" else "failed" if enrichment.status == "failed" else "completed",
            request_summary={
                "requestShape": sanitized_company_diagnostic_request_shape(diagnostics.get("requestShape") if isinstance(diagnostics.get("requestShape"), dict) else plan.search.sanitized_shape()),
                "requestedPages": diagnostics.get("requestedPages") or plan.search.max_pages,
                "limit": plan.search.limit,
            },
            result_summary={
                "fetchedPages": diagnostics.get("fetchedPages", 0),
                "failedPages": diagnostics.get("failedPages", 0),
                "skippedPages": diagnostics.get("skippedPages", 0),
                "rawCompanyCount": diagnostics.get("rawCompanyCount", 0),
                "normalizedCompanyCount": diagnostics.get("normalizedCompanyCount", 0),
                "upsertedCompanyCount": diagnostics.get("upsertedCompanyCount", 0),
                "duplicateCompanyCount": diagnostics.get("duplicateCompanyCount", 0),
                "totalResults": diagnostics.get("totalResults"),
            },
            error={"type": diagnostics.get("errorType"), "message": diagnostics.get("errorMessage") or enrichment.error_message}
            if enrichment.status in {"failed", "unavailable"} or diagnostics.get("errorMessage") or enrichment.error_message
            else None,
        )

        if plan.require_greenhouse:
            companies = link_filtered_theirstack_companies(
                self.session,
                candidate_profile_id=candidate_profile.id,
                enrichment=enrichment,
                discovery_query=latest_user_message,
                require_greenhouse=True,
                require_supported_ats=True,
            )
        elif plan.require_supported_ats:
            companies = link_filtered_theirstack_companies(
                self.session,
                candidate_profile_id=candidate_profile.id,
                enrichment=enrichment,
                discovery_query=latest_user_message,
                require_greenhouse=False,
                require_supported_ats=True,
            )
        else:
            companies = [
                link
                for link in enrichment.candidate_company_links
                if isinstance(link, CandidateCompany) and link.company is not None
            ]

        board_sync = run_post_enrichment_greenhouse_sync(
            self.session,
            settings=self.settings,
            plan=plan,
            linked_companies=companies,
        )
        ashby_sync = run_post_enrichment_ashby_sync(
            self.session,
            settings=self.settings,
            plan=plan,
            linked_companies=companies,
        )
        job_search = run_post_enrichment_synced_job_search(
            self.session,
            settings=self.settings,
            connector=active_connector,
            plan=plan,
            candidate_profile=candidate_profile,
            latest_user_message=latest_user_message,
            board_tokens=[
                *board_sync["board_tokens_synced"],
                *ashby_sync["board_tokens_synced"],
            ],
            source_providers=post_enrichment_synced_source_providers(board_sync, ashby_sync),
        )
        result_payload = build_enrichment_result_payload(
            plan=plan,
            validation_issues=validation_issues,
            enrichment=enrichment,
            linked_companies=companies,
            latest_user_message=latest_user_message,
            context=context,
            board_sync=board_sync,
            ashby_sync=ashby_sync,
            job_search=job_search,
        )
        record_company_discovery_provider_call(
            self.session,
            company_discovery_run_id=company_discovery_run_id,
            stage="persistence",
            provider="jobops_database",
            status="completed",
            label="TheirStack company link/upsert",
            result_summary={
                "upsertedCompanyCount": (enrichment.diagnostics or {}).get("upsertedCompanyCount", 0),
                "linkedCandidateCompanyCount": len(companies),
                "duplicateCompanyCount": (enrichment.diagnostics or {}).get("duplicateCompanyCount", 0),
                "filteredNoSupportedAtsCount": result_payload.get("filteredNoSupportedAtsCount"),
                "filteredNoGreenhouseTokenCount": result_payload.get("filteredNoGreenhouseTokenCount"),
            },
        )
        record_first_party_sync_diagnostics(self.session, company_discovery_run_id=company_discovery_run_id, provider="greenhouse", sync=board_sync)
        record_first_party_sync_diagnostics(self.session, company_discovery_run_id=company_discovery_run_id, provider="ashby", sync=ashby_sync)
        record_company_discovery_provider_call(
            self.session,
            company_discovery_run_id=company_discovery_run_id,
            stage="post_sync_job_search",
            provider="jobops_database",
            status="completed" if job_search["job_search_attempted"] else "skipped",
            label="Post-sync job search",
            request_summary={"attempted": job_search["job_search_attempted"]},
            result_summary={
                "jobSearchRunId": job_search["job_search_run_id"],
                "syncedJobQueryCount": job_search["synced_job_query_count"],
                "syncedJobPoolCount": job_search["synced_job_pool_count"],
                "jobsReviewed": job_search["jobs_reviewed_count"],
                "jobsAdded": job_search["jobs_added_count"],
                "jobsRecommended": job_search["jobs_recommended_count"],
                "jobsRejected": job_search["jobs_rejected_count"],
                "unavailableReason": job_search["search_unavailable_reason"],
            },
        )
        complete_company_discovery_run(
            self.session,
            company_discovery_run_id,
            status="completed" if enrichment.status in {"completed", "unavailable"} else "failed",
            source_path="theirstack_company_enrichment",
            source_provider="theirstack",
            model_provider=response.provider,
            model_name=response.model,
            saved_company_count=len(companies),
            linked_company_count=len(companies),
            skipped_company_count=max(0, len(enrichment.companies) - len(companies)),
            zero_new_company_reason=result_payload.get("zeroResultReason"),
            run_diagnostics_json={
                "searchQueriesUsed": [],
                "discoveryAngles": list(plan.hiring_signal_terms),
                "theirStack": result_payload.get("discoveryAudit", {}).get("theirStack") if isinstance(result_payload.get("discoveryAudit"), dict) else {},
                "firstPartySync": result_payload.get("discoveryAudit", {}).get("firstPartySync") if isinstance(result_payload.get("discoveryAudit"), dict) else {},
                "companies": result_payload.get("discoveryAudit", {}).get("companies") if isinstance(result_payload.get("discoveryAudit"), dict) else result_payload.get("companies", []),
                "diagnosticMessages": [],
            },
            error=(enrichment.diagnostics or {}).get("errorMessage") or enrichment.error_message,
        )
        log_event = "theirstack.company_search.completed" if enrichment.status in {"completed", "unavailable"} else "theirstack.company_search.failed"
        logger.info(
            log_event,
            extra={
                "candidate_profile_id": candidate_profile.id,
                "command_preview": compact_log_preview(latest_user_message),
                "source_path": "theirstack_company_enrichment",
                "theirstack_checked": True,
                "theirstack_enabled": bool((enrichment.diagnostics or {}).get("enabled", True)),
                "theirstack_used": enrichment.status != "unavailable",
                "request_shape": sanitized_company_diagnostic_request_shape((enrichment.diagnostics or {}).get("requestShape", {})),
                "raw_company_count": (enrichment.diagnostics or {}).get("rawCompanyCount"),
                "normalized_company_count": (enrichment.diagnostics or {}).get("normalizedCompanyCount"),
                "upserted_company_count": (enrichment.diagnostics or {}).get("upsertedCompanyCount"),
                "linked_company_count": len(companies),
                "board_sync_completed_count": result_payload.get("totalBoardSyncCompletedCount"),
                "board_sync_failed_count": result_payload.get("totalBoardSyncFailedCount"),
                "error_type": (enrichment.diagnostics or {}).get("errorType"),
                "error_message": (enrichment.diagnostics or {}).get("errorMessage") or enrichment.error_message,
            },
        )
        logger.info(
            "company_discovery.completed",
            extra={
                "candidate_profile_id": candidate_profile.id,
                "command_preview": compact_log_preview(latest_user_message),
                "source_path": "theirstack_company_enrichment",
                "linked_company_count": len(companies),
                "theirstack_used": enrichment.status != "unavailable",
            },
        )
        return CompanyEnrichmentServiceResult(
            handled=True,
            status_code=200 if enrichment.status in {"completed", "unavailable"} else 502,
            body={"ok": enrichment.status != "failed", "result": result_payload},
        )


def link_filtered_theirstack_companies(
    session: Session,
    *,
    candidate_profile_id: str,
    enrichment: Any,
    discovery_query: str,
    require_greenhouse: bool,
    require_supported_ats: bool,
) -> list[CandidateCompany]:
    links: list[CandidateCompany] = []
    seen_link_ids: set[str] = set()
    for company, normalized in zip(enrichment.companies, enrichment.normalized_companies, strict=False):
        if require_greenhouse and not getattr(company, "greenhouse_board_token", None):
            continue
        if require_supported_ats and not company_has_supported_ats(company):
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
        if link_result.link.id not in seen_link_ids:
            seen_link_ids.add(link_result.link.id)
            links.append(link_result.link)
    return links


def company_has_supported_ats(company: Any) -> bool:
    return bool(
        getattr(company, "greenhouse_board_token", None)
        or getattr(company, "ashby_board_url", None)
        or getattr(company, "lever_slug", None)
    )


def plan_requests_any_board_sync(plan: CompanyEnrichmentPlan) -> bool:
    return bool(plan.sync_discovered_ats_boards or plan.sync_discovered_greenhouse_boards or plan.sync_discovered_ashby_boards)


def run_post_enrichment_greenhouse_sync(
    session: Session,
    *,
    settings: Settings,
    plan: CompanyEnrichmentPlan,
    linked_companies: list[CandidateCompany],
) -> dict[str, Any]:
    tokens = unique_greenhouse_board_tokens(linked_companies)
    sync_requested = bool(plan.sync_discovered_greenhouse_boards or plan.sync_discovered_ats_boards)
    diagnostics = {
        "greenhouse_board_token_count": len(tokens),
        "boards_detected": tokens,
        "boards_selected_for_sync": tokens if sync_requested else [],
        "board_tokens_synced": [],
        "board_sync_attempted": False,
        "board_sync_completed_count": 0,
        "board_sync_failed_count": 0,
        "board_sync_raw_result_count": 0,
        "board_sync_normalized_count": 0,
        "board_sync_created_count": 0,
        "board_sync_updated_count": 0,
        "board_sync_skipped_fresh_count": 0,
        "sync_unavailable_reason": None,
        "job_sync_results": (),
    }
    if not sync_requested:
        diagnostics["sync_unavailable_reason"] = "sync_not_requested"
        return diagnostics
    if not tokens:
        diagnostics["sync_unavailable_reason"] = "no_greenhouse_board_tokens"
        return diagnostics

    results = tuple(
        sync_greenhouse_boards(
            session,
            settings=settings,
            board_tokens=tokens,
            include_configured=False,
            force=False,
            freshness_hours=24,
        )
    )
    diagnostics.update(
        {
            "board_sync_attempted": True,
            "board_tokens_synced": [
                result.request.ats_board_token
                for result in results
                if getattr(result, "request", None) is not None
                and result.request.ats_board_token
                and result.status != "failed"
            ],
            "board_sync_completed_count": sum(1 for result in results if result.status == "completed"),
            "board_sync_failed_count": sum(1 for result in results if result.status == "failed"),
            "board_sync_raw_result_count": sum(int(getattr(result, "raw_result_count", 0) or 0) for result in results),
            "board_sync_normalized_count": sum(int(getattr(result, "normalized_count", 0) or 0) for result in results),
            "board_sync_created_count": sum(int(getattr(result, "created_count", 0) or 0) for result in results),
            "board_sync_updated_count": sum(int(getattr(result, "updated_count", 0) or 0) for result in results),
            "board_sync_skipped_fresh_count": sum(1 for result in results if str(getattr(result, "status", "")).startswith("skipped")),
            "job_sync_results": results,
        }
    )
    return diagnostics


def run_post_enrichment_ashby_sync(
    session: Session,
    *,
    settings: Settings,
    plan: CompanyEnrichmentPlan,
    linked_companies: list[CandidateCompany],
) -> dict[str, Any]:
    board_urls = unique_ashby_board_urls(linked_companies)
    sync_requested = bool(plan.sync_discovered_ashby_boards or plan.sync_discovered_ats_boards)
    diagnostics = {
        "ashby_board_url_count": len(board_urls),
        "boards_detected": board_urls,
        "boards_selected_for_sync": board_urls if sync_requested else [],
        "board_tokens_synced": [],
        "board_urls_synced": [],
        "board_sync_attempted": False,
        "board_sync_completed_count": 0,
        "board_sync_failed_count": 0,
        "board_sync_raw_result_count": 0,
        "board_sync_normalized_count": 0,
        "board_sync_created_count": 0,
        "board_sync_updated_count": 0,
        "board_sync_skipped_fresh_count": 0,
        "sync_unavailable_reason": None,
        "job_sync_results": (),
    }
    if not sync_requested:
        diagnostics["sync_unavailable_reason"] = "sync_not_requested"
        return diagnostics
    if not board_urls:
        diagnostics["sync_unavailable_reason"] = "no_ashby_board_urls"
        return diagnostics

    results = tuple(
        sync_ashby_boards(
            session,
            settings=settings,
            board_urls=board_urls,
            include_configured=False,
            force=False,
            freshness_hours=24,
        )
    )
    diagnostics.update(
        {
            "board_sync_attempted": True,
            "board_tokens_synced": [
                result.request.ats_board_token
                for result in results
                if getattr(result, "request", None) is not None
                and result.request.ats_board_token
                and result.status != "failed"
            ],
            "board_urls_synced": [
                result.request.criteria_json.get("boardUrl")
                for result in results
                if getattr(result, "request", None) is not None
                and result.request.criteria_json
                and result.request.criteria_json.get("boardUrl")
                and result.status != "failed"
            ],
            "board_sync_completed_count": sum(1 for result in results if result.status == "completed"),
            "board_sync_failed_count": sum(1 for result in results if result.status == "failed"),
            "board_sync_raw_result_count": sum(int(getattr(result, "raw_result_count", 0) or 0) for result in results),
            "board_sync_normalized_count": sum(int(getattr(result, "normalized_count", 0) or 0) for result in results),
            "board_sync_created_count": sum(int(getattr(result, "created_count", 0) or 0) for result in results),
            "board_sync_updated_count": sum(int(getattr(result, "updated_count", 0) or 0) for result in results),
            "board_sync_skipped_fresh_count": sum(1 for result in results if str(getattr(result, "status", "")).startswith("skipped")),
            "job_sync_results": results,
        }
    )
    return diagnostics


def post_enrichment_synced_source_providers(board_sync: dict[str, Any], ashby_sync: dict[str, Any]) -> tuple[str, ...]:
    providers: list[str] = []
    if board_sync["board_tokens_synced"]:
        providers.append("greenhouse")
    if ashby_sync["board_tokens_synced"]:
        providers.append("ashby")
    return tuple(providers)


def run_post_enrichment_synced_job_search(
    session: Session,
    *,
    settings: Settings,
    connector: ModelConnector | None,
    plan: CompanyEnrichmentPlan,
    candidate_profile: CandidateProfile,
    latest_user_message: str,
    board_tokens: list[str],
    source_providers: tuple[str, ...],
) -> dict[str, Any]:
    empty = {
        "job_search_attempted": False,
        "job_search_run_id": None,
        "synced_job_query_count": 0,
        "synced_job_pool_count": 0,
        "jobs_reviewed_count": 0,
        "jobs_added_count": 0,
        "jobs_recommended_count": 0,
        "jobs_rejected_count": 0,
        "added_job_ids": [],
        "added_job_listing_ids": [],
        "recommended_job_listing_ids": [],
        "model_review_completed": False,
        "model_review_failure_reason": None,
        "search_unavailable_reason": None,
        "assistant_message": None,
    }
    if not plan.search_synced_jobs_after_board_sync:
        empty["search_unavailable_reason"] = "search_not_requested"
        return empty
    if not board_tokens or not source_providers:
        empty["search_unavailable_reason"] = "no_synced_supported_ats_boards"
        return empty

    query = build_post_enrichment_job_query(plan, board_tokens=tuple(board_tokens), source_providers=source_providers)
    search_plan = DbJobSearchPlan(
        mode="new_job_discovery",
        job_scope="new_to_candidate",
        mode_rationale="Search first-party ATS jobs synced from enriched company boards.",
        queries=(query,),
        min_job_pool_size=1,
        max_job_pool_size=300,
        max_jobs_for_model_review=settings.job_discovery_candidate_pool_limit or 80,
    )
    run = JobSearchRun(
        candidate_profile_id=candidate_profile.id,
        command_text=latest_user_message,
        search_plan_json={
            "source": "company_enrichment_post_ats_sync",
            "syncDiscoveredGreenhouseBoards": plan.sync_discovered_greenhouse_boards,
            "syncDiscoveredAshbyBoards": plan.sync_discovered_ashby_boards,
            "syncDiscoveredAtsBoards": plan.sync_discovered_ats_boards,
            "searchSyncedJobsAfterBoardSync": plan.search_synced_jobs_after_board_sync,
            "saveMatchingJobsToCandidateList": plan.save_matching_jobs_to_candidate_list,
            "recommendOnly": plan.recommend_only,
            "sourceProviders": list(source_providers),
            "queries": [query.__dict__],
        },
        run_diagnostics_json={},
        provider_names=[*source_providers, "database", "model_review"],
        search_mode="company_enrichment_post_sync",
        status="running",
        started_at=datetime.now(UTC),
    )
    session.add(run)
    session.flush()

    query_builder = JobListingQueryBuilder(session)
    job_listings, query_counts = query_builder.execute_plan(candidate_profile.id, search_plan)
    persist_post_enrichment_query_runs(session, run.id, query_counts, deduped_count=len(job_listings), query=query)
    pool_entries = build_post_enrichment_pool_entries(session, job_listings)
    review = JobReviewSelector().review(
        JobDiscoveryRequest(latest_user_message=latest_user_message, candidate_profile_slug=candidate_profile.slug),
        connector=connector,
        settings=settings,
        job_pool=pool_entries,
        max_selected=settings.job_discovery_save_limit,
        review_mode="select_new_jobs",
        requested_count=settings.job_discovery_save_limit,
        allow_rejections=not plan.recommend_only,
    )
    review = validate_review_result(review, tuple(entry.job_listing_id for entry in pool_entries))
    model_review_completed = bool(review.diagnostics.get("modelReviewCompleted", True))
    selected_links = []
    updated_links = []
    rejected_links = []
    if plan.save_matching_jobs_to_candidate_list and not plan.recommend_only and model_review_completed:
        selected_links, updated_links, rejected_links = CandidateJobRepository(session).apply_review_result(
            candidate_profile_id=candidate_profile.id,
            job_search_run_id=run.id,
            review=review,
        )

    run.status = "completed"
    run.completed_at = datetime.now(UTC)
    run.total_provider_results = 0
    run.candidate_pool_count = len(job_listings)
    run.candidate_count_after_dedupe = len(job_listings)
    run.model_selected_count = len(review.selected_jobs)
    run.saved_count = len(selected_links)
    run.updated_existing_count = len(updated_links)
    run.duplicate_count = 0
    run.skipped_count = len(rejected_links)
    run.provider_error_count = 0
    run.run_diagnostics_json = {
        "source": "company_enrichment_post_ats_sync",
        "sourceProviders": list(source_providers),
        "queryCounts": [{"label": label, "jobCount": count} for label, count in query_counts],
        "syncedJobPoolCount": len(job_listings),
        "jobsReviewedCount": len(pool_entries) if model_review_completed else 0,
        "jobsAddedCount": len(selected_links),
        "jobsRejectedCount": len(rejected_links),
        "rejectionReasonCounts": rejection_reason_counts(rejected_links),
        "modelReview": review.diagnostics,
        "addedJobIds": [link.id for link in selected_links],
        "addedJobListingIds": [link.job_listing_id for link in selected_links if link.job_listing_id],
    }
    session.flush()
    return {
        **empty,
        "job_search_attempted": True,
        "job_search_run_id": run.id,
        "synced_job_query_count": len(query_counts),
        "synced_job_pool_count": len(job_listings),
        "jobs_reviewed_count": len(pool_entries) if model_review_completed else 0,
        "jobs_added_count": len(selected_links),
        "jobs_recommended_count": len(review.selected_jobs) if plan.recommend_only else 0,
        "jobs_rejected_count": len(rejected_links),
        "added_job_ids": [link.id for link in selected_links],
        "added_job_listing_ids": [link.job_listing_id for link in selected_links if link.job_listing_id],
        "recommended_job_listing_ids": [decision.job_listing_id for decision in review.selected_jobs] if plan.recommend_only else [],
        "model_review_completed": model_review_completed,
        "model_review_failure_reason": review.diagnostics.get("modelReviewFailureReason"),
        "assistant_message": review.user_visible_summary,
    }


def build_post_enrichment_job_query(
    plan: CompanyEnrichmentPlan,
    *,
    board_tokens: tuple[str, ...],
    source_providers: tuple[str, ...],
) -> DbJobSearchQuery:
    title_terms = tuple(
        compact_strings(
            [
                *[str(item) for item in plan.search.job_filters.get("job_title_pattern_or", []) if str(item).strip()],
                *plan.hiring_signal_terms,
            ],
            limit=12,
        )
    )
    return DbJobSearchQuery(
        label="Search first-party synced jobs from enriched company boards",
        source_providers_any=source_providers,
        ats_board_tokens_any=board_tokens,
        title_terms_any=title_terms,
        source_statuses_any=("active",),
        limit=300,
        order_by="last_seen_at_desc",
    )


def persist_post_enrichment_query_runs(
    session: Session,
    job_search_run_id: str,
    query_counts: tuple[tuple[str, int], ...],
    *,
    deduped_count: int,
    query: DbJobSearchQuery,
) -> None:
    for label, count in query_counts:
        session.add(
            JobSearchQueryRun(
                job_search_run_id=job_search_run_id,
                provider_name="database",
                query=label,
                total_matches=count,
                raw_result_count=count,
                normalized_result_count=count,
                deduped_result_count=deduped_count,
                candidate_count_after_filters=count,
                error=None,
                location=", ".join(query.location_display_terms_any) or None,
            )
        )
    session.flush()


def build_post_enrichment_pool_entries(session: Session, job_listings: list[Any]) -> list[JobPoolEntry]:
    if not job_listings:
        return []
    provider_map: dict[str, list[str]] = {}

    for source in session.scalars(
        select(JobListingSource).where(JobListingSource.job_listing_id.in_([job.id for job in job_listings]))
    ).all():
        provider_map.setdefault(source.job_listing_id, [])
        if source.source_provider not in provider_map[source.job_listing_id]:
            provider_map[source.job_listing_id].append(source.source_provider)
    return [
        job_listing_to_pool_entry(job, source_providers=tuple(provider_map.get(job.id, ())))
        for job in job_listings
    ]


def unique_greenhouse_board_tokens(links: list[CandidateCompany]) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for link in links:
        token = (getattr(getattr(link, "company", None), "greenhouse_board_token", None) or "").strip()
        key = token.casefold()
        if token and key not in seen:
            tokens.append(token)
            seen.add(key)
    return tokens


def unique_ashby_board_urls(links: list[CandidateCompany]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for link in links:
        parsed = parse_ashby_job_board_url(getattr(getattr(link, "company", None), "ashby_board_url", None))
        if parsed and parsed.org_slug.casefold() not in seen:
            urls.append(parsed.canonical_board_url)
            seen.add(parsed.org_slug.casefold())
    return urls


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
            "can_sync_discovered_greenhouse_boards": True,
            "can_sync_discovered_ashby_boards": True,
            "can_sync_discovered_ats_boards": ["greenhouse", "ashby"],
            "can_search_synced_jobs_after_board_sync": True,
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
- If the user asks to act on discovered company leads by finding jobs from them, set syncDiscoveredAtsBoards=true
  and searchSyncedJobsAfterBoardSync=true. Set saveMatchingJobsToCandidateList=true only when the user asks to add
  matching jobs or find jobs to apply to. Use provider-specific sync fields only when the user explicitly constrains
  the request to Greenhouse or Ashby.

Planning rules:
- If the user explicitly asks for Greenhouse companies or companies with Greenhouse boards, set requireGreenhouse=true.
- For requests like "find companies with Greenhouse boards and then find jobs from them", "find companies like
  Hightouch and look for jobs", or "find jobs from companies discovered through TheirStack", keep TheirStack as the
  company lead source, then request first-party ATS board sync through syncDiscoveredAtsBoards.
- Do not describe TheirStack job snippets as verified jobs. Only post-sync Greenhouse or Ashby JobListing rows are actual jobs
  that may be searched, recommended, or added to the jobs list.
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
  "syncDiscoveredAtsBoards": false,
  "syncDiscoveredGreenhouseBoards": false,
  "syncDiscoveredAshbyBoards": false,
  "searchSyncedJobsAfterBoardSync": false,
  "saveMatchingJobsToCandidateList": false,
  "recommendOnly": false,
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
            "syncDiscoveredAtsBoards": False,
            "syncDiscoveredGreenhouseBoards": False,
            "syncDiscoveredAshbyBoards": False,
            "searchSyncedJobsAfterBoardSync": False,
            "saveMatchingJobsToCandidateList": False,
            "recommendOnly": False,
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
    board_sync: dict[str, Any],
    ashby_sync: dict[str, Any],
    job_search: dict[str, Any],
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
    filtered_no_supported_ats_count = (
        max(0, len(enrichment.companies) - len(linked_companies))
        if plan.require_supported_ats and not plan.require_greenhouse
        else 0
    )
    message = build_enrichment_assistant_message(
        linked_count=len(linked_companies),
        greenhouse_count=greenhouse_count,
        filtered_no_greenhouse_count=filtered_no_greenhouse_count,
        filtered_no_supported_ats_count=filtered_no_supported_ats_count,
        require_greenhouse=plan.require_greenhouse,
        require_supported_ats=plan.require_supported_ats,
        board_sync=board_sync,
        ashby_sync=ashby_sync,
        job_search=job_search,
    )
    total_board_sync_completed_count = board_sync["board_sync_completed_count"] + ashby_sync["board_sync_completed_count"]
    total_board_sync_failed_count = board_sync["board_sync_failed_count"] + ashby_sync["board_sync_failed_count"]
    total_board_sync_normalized_count = board_sync["board_sync_normalized_count"] + ashby_sync["board_sync_normalized_count"]
    discovery_audit = build_theirstack_discovery_audit(
        plan=plan,
        enrichment=enrichment,
        linked_companies=companies_payload,
        board_sync=board_sync,
        ashby_sync=ashby_sync,
        job_search=job_search,
        total_board_sync_completed_count=total_board_sync_completed_count,
        total_board_sync_failed_count=total_board_sync_failed_count,
        total_board_sync_normalized_count=total_board_sync_normalized_count,
    )
    return {
        "assistantMessage": message,
        "companies": companies_payload,
        "discoveryAudit": discovery_audit,
        "providerDiagnostics": discovery_audit["providerDiagnostics"],
        "enrichedCompanyCount": len(enrichment.companies),
        "rawCompanyCount": (enrichment.diagnostics or {}).get("rawCompanyCount"),
        "normalizedCompanyCount": (enrichment.diagnostics or {}).get("normalizedCompanyCount"),
        "upsertedCompanyCount": (enrichment.diagnostics or {}).get("upsertedCompanyCount"),
        "linkedCompanyCount": len(linked_companies),
        "filteredNoGreenhouseTokenCount": filtered_no_greenhouse_count,
        "filteredNoSupportedAtsCount": filtered_no_supported_ats_count,
        "greenhouseBoardTokenCount": greenhouse_count,
        "boardsSelectedForSync": board_sync["boards_selected_for_sync"],
        "boardTokensSynced": board_sync["board_tokens_synced"],
        "boardSyncAttempted": board_sync["board_sync_attempted"],
        "boardSyncCompletedCount": board_sync["board_sync_completed_count"],
        "boardSyncFailedCount": board_sync["board_sync_failed_count"],
        "boardSyncRawResultCount": board_sync["board_sync_raw_result_count"],
        "boardSyncNormalizedCount": board_sync["board_sync_normalized_count"],
        "boardSyncCreatedCount": board_sync["board_sync_created_count"],
        "boardSyncUpdatedCount": board_sync["board_sync_updated_count"],
        "boardSyncSkippedFreshCount": board_sync["board_sync_skipped_fresh_count"],
        "syncUnavailableReason": board_sync["sync_unavailable_reason"],
        "ashbyBoardsSelectedForSync": ashby_sync["boards_selected_for_sync"],
        "ashbyBoardTokensSynced": ashby_sync["board_tokens_synced"],
        "ashbyBoardUrlsSynced": ashby_sync["board_urls_synced"],
        "ashbyBoardSyncAttempted": ashby_sync["board_sync_attempted"],
        "ashbyBoardSyncCompletedCount": ashby_sync["board_sync_completed_count"],
        "ashbyBoardSyncFailedCount": ashby_sync["board_sync_failed_count"],
        "ashbyBoardSyncRawResultCount": ashby_sync["board_sync_raw_result_count"],
        "ashbyBoardSyncNormalizedCount": ashby_sync["board_sync_normalized_count"],
        "ashbyBoardSyncCreatedCount": ashby_sync["board_sync_created_count"],
        "ashbyBoardSyncUpdatedCount": ashby_sync["board_sync_updated_count"],
        "ashbyBoardSyncSkippedFreshCount": ashby_sync["board_sync_skipped_fresh_count"],
        "ashbySyncUnavailableReason": ashby_sync["sync_unavailable_reason"],
        "totalBoardSyncCompletedCount": total_board_sync_completed_count,
        "totalBoardSyncFailedCount": total_board_sync_failed_count,
        "totalBoardSyncNormalizedCount": total_board_sync_normalized_count,
        "searchSyncedJobsAttempted": job_search["job_search_attempted"],
        "postEnrichmentJobSearchRunId": job_search["job_search_run_id"],
        "syncedJobQueryCount": job_search["synced_job_query_count"],
        "syncedJobPoolCount": job_search["synced_job_pool_count"],
        "jobsReviewedAfterBoardSyncCount": job_search["jobs_reviewed_count"],
        "jobsAddedAfterBoardSyncCount": job_search["jobs_added_count"],
        "jobsRecommendedAfterBoardSyncCount": job_search["jobs_recommended_count"],
        "jobsRejectedAfterBoardSyncCount": job_search["jobs_rejected_count"],
        "addedJobIds": job_search["added_job_ids"],
        "addedJobListingIds": job_search["added_job_listing_ids"],
        "recommendedJobListingIds": job_search["recommended_job_listing_ids"],
        "postBoardSyncJobSearchUnavailableReason": job_search["search_unavailable_reason"],
        "ashbyBoardUrlCount": ashby_count,
        "leverSlugCount": lever_count,
        "unsupportedAtsUrlCount": unsupported_count,
        "hiringSignalSource": plan.hiring_signal_source,
        "hiringSignalQuery": latest_user_message,
        "jobFiltersUsed": plan.search.job_filters,
        "jobsFoundCount": jobs_found_count,
        "exampleMatchingJobTitles": [],
        "requiresFirstPartySyncForVerification": plan.requires_first_party_sync_for_verification,
        "theirstackDiagnostics": sanitized_theirstack_diagnostics(enrichment.diagnostics),
        "companyEnrichmentPlan": serialize_plan(plan),
        "companyEnrichmentValidationIssues": validation_issues,
        "zeroResultReason": None if linked_companies else ("theirstackUnavailable" if enrichment.status == "unavailable" else "noTheirStackCompanyLeadsLinked"),
        "clarifyingQuestions": [],
        "sourceCaveat": (
            "TheirStack returned company hiring signals. Jobs are verified only after first-party Greenhouse or Ashby board sync."
            if board_sync["board_sync_attempted"] or ashby_sync["board_sync_attempted"]
            else "TheirStack returned hiring signals; JobOps has not synced first-party company boards for verification yet."
        ),
    }


def build_clarifying_result_payload(
    plan: CompanyEnrichmentPlan,
    validation_issues: list[dict[str, Any]],
    context: dict[str, Any],
) -> dict[str, Any]:
    questions = list(plan.clarifying_questions) or ["What kind of companies should I enrich or discover?"]
    discovery_audit = build_clarifying_discovery_audit(plan, validation_issues)
    return {
        "assistantMessage": questions[0],
        "companies": [],
        "discoveryAudit": discovery_audit,
        "providerDiagnostics": discovery_audit["providerDiagnostics"],
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
    filtered_no_supported_ats_count: int,
    require_greenhouse: bool,
    require_supported_ats: bool,
    board_sync: dict[str, Any],
    ashby_sync: dict[str, Any],
    job_search: dict[str, Any],
) -> str:
    if linked_count == 0:
        return (
            "I did not add company leads from TheirStack. TheirStack hiring signals are not verified JobOps board matches, "
            "and first-party board sync is still required before treating them as current openings."
        )
    if board_sync["board_sync_attempted"] or ashby_sync["board_sync_attempted"]:
        ashby_count = len(ashby_sync["boards_selected_for_sync"])
        synced_job_count = board_sync["board_sync_normalized_count"] + ashby_sync["board_sync_normalized_count"]
        provider_parts = []
        if greenhouse_count:
            provider_parts.append(f"{greenhouse_count} Greenhouse board{'s' if greenhouse_count != 1 else ''}")
        if ashby_count:
            provider_parts.append(f"{ashby_count} Ashby board{'s' if ashby_count != 1 else ''}")
        provider_summary = " and ".join(provider_parts) if provider_parts else "no supported ATS boards"
        base = (
            f"I enriched {linked_count} company lead{'s' if linked_count != 1 else ''} and found {provider_summary}. "
            f"I synced those first-party boards and found {synced_job_count} active job"
            f"{'s' if synced_job_count != 1 else ''}."
        )
        if job_search["job_search_attempted"]:
            if job_search["jobs_added_count"]:
                return (
                    f"{base} I added {job_search['jobs_added_count']} matching job"
                    f"{'s' if job_search['jobs_added_count'] != 1 else ''} to your jobs list."
                )
            return f"{base} I did not add jobs because model review did not select matching synced jobs."
        return base
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
    if require_supported_ats:
        filtered_sentence = (
            f" I filtered out {filtered_no_supported_ats_count} TheirStack compan"
            f"{'y' if filtered_no_supported_ats_count == 1 else 'ies'} without supported ATS metadata."
            if filtered_no_supported_ats_count
            else ""
        )
        return (
            f"I added only companies with supported ATS metadata as leads: {linked_count} {company_word}. "
            f"{greenhouse_count} include Greenhouse board tokens.{filtered_sentence} "
            "I have not synced those boards yet, so these are leads for first-party verification."
        )
    return (
        f"I found {linked_count} {company_word} TheirStack returned for hiring signals related to your request. "
        f"{greenhouse_count} include Greenhouse board tokens. I have not synced those boards yet, so these are leads for first-party verification."
    )


def serialize_enriched_company(link: CandidateCompany) -> dict[str, Any]:
    company = link.company
    metadata = link.provider_grounding_metadata if isinstance(link.provider_grounding_metadata, dict) else {}
    company_metadata = metadata.get("companyMetadata") if isinstance(metadata.get("companyMetadata"), dict) else {}
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
        "discovered_by": link.discovered_by,
        "discoverySource": "theirstack",
        "discoverySourceLabel": "TheirStack",
        "dataOriginSource": "theirstack",
        "dataOriginSourceType": "provider",
        "dataOriginSourceLabel": "TheirStack company search",
        "provider_grounding_metadata_summary": {
            key: value
            for key, value in {
                "provider": metadata.get("provider"),
                "discoveryQuery": metadata.get("discoveryQuery"),
                "industry": company_metadata.get("industry"),
                "employeeCount": company_metadata.get("employeeCount"),
                "employeeCountRange": company_metadata.get("employeeCountRange"),
                "fundingStage": company_metadata.get("fundingStage"),
                "totalFundingUsd": company_metadata.get("totalFundingUsd"),
                "technologyNames": company_metadata.get("technologyNames"),
                "technologySlugs": company_metadata.get("technologySlugs"),
                "keywordSlugs": company_metadata.get("keywordSlugs"),
                "numJobsFound": company_metadata.get("numJobsFound"),
                "atsInference": metadata.get("atsInference"),
            }.items()
            if value not in (None, [], {})
        },
    }


def build_company_enrichment_provider_diagnostic(
    *,
    stage: str,
    provider: str,
    status: str,
    label: str,
    request_summary: dict[str, Any] | None = None,
    result_summary: dict[str, Any] | None = None,
    error: str | dict[str, Any] | None = None,
) -> dict[str, Any]:
    from .company_discovery import build_company_provider_diagnostic

    return build_company_provider_diagnostic(
        stage=stage,
        provider=provider,
        status=status,
        label=label,
        request_summary=request_summary,
        result_summary=result_summary,
        error=error,
    )


def build_clarifying_discovery_audit(plan: CompanyEnrichmentPlan, validation_issues: list[dict[str, Any]]) -> dict[str, Any]:
    provider_diagnostics = [
        build_company_enrichment_provider_diagnostic(
            stage="planner",
            provider="model",
            status="completed",
            label="Company enrichment planner",
            request_summary={"useTheirStackCompanySearch": plan.use_theirstack_company_search},
            result_summary={
                "requiresClarification": True,
                "validationIssueCodes": [issue.get("code") for issue in validation_issues if isinstance(issue.get("code"), str)],
            },
        )
    ]
    if any(issue.get("code") == "theirstack_unavailable" for issue in validation_issues):
        provider_diagnostics.append(
            build_company_enrichment_provider_diagnostic(
                stage="company_source",
                provider="theirstack",
                status="skipped",
                label="TheirStack company search",
                request_summary={"enabled": False, "requestShape": plan.search.sanitized_shape()},
                result_summary={"skippedReason": "missing_api_key", "unavailable": True},
                error={"message": "TheirStack company search is not configured."},
            )
        )
    return {
        "sourcePath": "theirstack_company_enrichment",
        "routerAction": "company_discovery",
        "sourceProvider": "theirstack",
        "searchGroundingEnabled": None,
        "modelProvider": None,
        "modelName": None,
        "savedCompanyCount": 0,
        "linkedCompanyCount": 0,
        "duplicateCompanyCount": 0,
        "skippedCompanyCount": 0,
        "zeroNewCompanyReason": "clarificationNeeded",
        "searchQueriesUsed": [],
        "discoveryAngles": list(plan.hiring_signal_terms),
        "companyDiscoveryPreflightBlocked": False,
        "preflightReason": None,
        "theirStack": {
            "checked": True,
            "enabled": False,
            "used": False,
            "skippedReason": "missing_api_key" if any(issue.get("code") == "theirstack_unavailable" for issue in validation_issues) else "clarification_needed",
            "requestShape": sanitized_company_diagnostic_request_shape(plan.search.sanitized_shape()),
            "requestedPages": 0,
            "fetchedPages": 0,
            "failedPages": 0,
            "skippedPages": 0,
            "rawCompanyCount": 0,
            "normalizedCompanyCount": 0,
            "upsertedCompanyCount": 0,
            "linkedCandidateCompanyCount": 0,
            "errorType": None,
            "errorMessage": None,
        },
        "firstPartySync": {
            "attempted": False,
            "providers": [],
            "greenhouseBoardsSelected": [],
            "greenhouseBoardsSynced": [],
            "ashbyBoardsSelected": [],
            "ashbyBoardsSynced": [],
            "completedCount": 0,
            "failedCount": 0,
            "normalizedJobCount": 0,
        },
        "providerDiagnostics": provider_diagnostics,
        "companies": [],
        "diagnosticMessages": [],
    }


def build_theirstack_discovery_audit(
    *,
    plan: CompanyEnrichmentPlan,
    enrichment: Any,
    linked_companies: list[dict[str, Any]],
    board_sync: dict[str, Any],
    ashby_sync: dict[str, Any],
    job_search: dict[str, Any],
    total_board_sync_completed_count: int,
    total_board_sync_failed_count: int,
    total_board_sync_normalized_count: int,
) -> dict[str, Any]:
    diagnostics = enrichment.diagnostics if isinstance(enrichment.diagnostics, dict) else {}
    status = enrichment.status
    used = status != "unavailable"
    their_stack_summary = {
        "checked": True,
        "enabled": bool(diagnostics.get("enabled", used)),
        "used": used,
        "skippedReason": None if used else "missing_api_key",
        "requestShape": sanitized_company_diagnostic_request_shape(
            diagnostics.get("requestShape") if isinstance(diagnostics.get("requestShape"), dict) else plan.search.sanitized_shape()
        ),
        "requestedPages": diagnostics.get("requestedPages", 0),
        "fetchedPages": diagnostics.get("fetchedPages", 0),
        "failedPages": diagnostics.get("failedPages", 0),
        "skippedPages": diagnostics.get("skippedPages", 0),
        "pageNumbersFetched": diagnostics.get("pageNumbersFetched") or diagnostics.get("page_numbers_fetched"),
        "rawCompanyCount": diagnostics.get("rawCompanyCount", 0),
        "normalizedCompanyCount": diagnostics.get("normalizedCompanyCount", 0),
        "upsertedCompanyCount": diagnostics.get("upsertedCompanyCount", 0),
        "duplicateCompanyCount": diagnostics.get("duplicateCompanyCount", 0),
        "linkedCandidateCompanyCount": diagnostics.get("linkedCandidateCompanyCount", len(linked_companies)),
        "totalCompanies": diagnostics.get("totalCompanies"),
        "totalResults": diagnostics.get("totalResults"),
        "creditsUsed": diagnostics.get("creditsUsed"),
        "creditsRemaining": diagnostics.get("creditsRemaining"),
        "errorType": diagnostics.get("errorType"),
        "errorMessage": diagnostics.get("errorMessage") or enrichment.error_message,
    }
    provider_diagnostics = build_theirstack_provider_diagnostics(
        plan=plan,
        status=status,
        their_stack_summary=their_stack_summary,
        linked_company_count=len(linked_companies),
        skipped_company_count=max(0, len(enrichment.companies) - len(linked_companies)),
        board_sync=board_sync,
        ashby_sync=ashby_sync,
        job_search=job_search,
        total_board_sync_completed_count=total_board_sync_completed_count,
        total_board_sync_failed_count=total_board_sync_failed_count,
        total_board_sync_normalized_count=total_board_sync_normalized_count,
    )
    return {
        "sourcePath": "theirstack_company_enrichment",
        "routerAction": "company_discovery",
        "sourceProvider": "theirstack",
        "searchGroundingEnabled": None,
        "modelProvider": None,
        "modelName": None,
        "savedCompanyCount": len(linked_companies),
        "linkedCompanyCount": len(linked_companies),
        "duplicateCompanyCount": diagnostics.get("duplicateCompanyCount", 0),
        "skippedCompanyCount": max(0, len(enrichment.companies) - len(linked_companies)),
        "zeroNewCompanyReason": None if linked_companies else ("theirstackUnavailable" if status == "unavailable" else "noTheirStackCompanyLeadsLinked"),
        "searchQueriesUsed": [],
        "discoveryAngles": list(plan.hiring_signal_terms),
        "companyDiscoveryPreflightBlocked": False,
        "preflightReason": None,
        "theirStack": their_stack_summary,
        "firstPartySync": {
            "attempted": bool(board_sync["board_sync_attempted"] or ashby_sync["board_sync_attempted"]),
            "providers": [
                provider
                for provider, attempted in (
                    ("greenhouse", bool(board_sync["board_sync_attempted"])),
                    ("ashby", bool(ashby_sync["board_sync_attempted"])),
                )
                if attempted
            ],
            "greenhouseBoardsSelected": board_sync["boards_selected_for_sync"],
            "greenhouseBoardsSynced": board_sync["board_tokens_synced"],
            "ashbyBoardsSelected": ashby_sync["boards_selected_for_sync"],
            "ashbyBoardsSynced": ashby_sync["board_urls_synced"],
            "completedCount": total_board_sync_completed_count,
            "failedCount": total_board_sync_failed_count,
            "normalizedJobCount": total_board_sync_normalized_count,
        },
        "providerDiagnostics": provider_diagnostics,
        "companies": [
            {
                "name": company.get("name"),
                "discoverySource": company.get("discoverySource"),
                "dataOriginSource": company.get("dataOriginSource"),
                "dataOriginSourceType": company.get("dataOriginSourceType"),
                "greenhouseBoardToken": company.get("greenhouse_board_token"),
                "ashbyBoardUrl": company.get("ashby_board_url"),
                "jobsFoundSignal": (company.get("provider_grounding_metadata_summary") or {}).get("numJobsFound")
                if isinstance(company.get("provider_grounding_metadata_summary"), dict)
                else None,
            }
            for company in linked_companies
        ],
        "diagnosticMessages": [],
    }


def build_theirstack_provider_diagnostics(
    *,
    plan: CompanyEnrichmentPlan,
    status: str,
    their_stack_summary: dict[str, Any],
    linked_company_count: int,
    skipped_company_count: int,
    board_sync: dict[str, Any],
    ashby_sync: dict[str, Any],
    job_search: dict[str, Any],
    total_board_sync_completed_count: int,
    total_board_sync_failed_count: int,
    total_board_sync_normalized_count: int,
) -> list[dict[str, Any]]:
    rows = [
        build_company_enrichment_provider_diagnostic(
            stage="planner",
            provider="model",
            status="completed",
            label="Company enrichment planner",
            request_summary={"hiringSignalSource": plan.hiring_signal_source},
            result_summary={
                "useTheirStackCompanySearch": plan.use_theirstack_company_search,
                "requireSupportedAts": plan.require_supported_ats,
                "requireGreenhouse": plan.require_greenhouse,
                "syncDiscoveredAtsBoards": plan.sync_discovered_ats_boards,
                "syncDiscoveredGreenhouseBoards": plan.sync_discovered_greenhouse_boards,
                "syncDiscoveredAshbyBoards": plan.sync_discovered_ashby_boards,
                "searchSyncedJobsAfterBoardSync": plan.search_synced_jobs_after_board_sync,
                "saveMatchingJobsToCandidateList": plan.save_matching_jobs_to_candidate_list,
            },
        ),
        build_company_enrichment_provider_diagnostic(
            stage="company_source",
            provider="theirstack",
            status="failed" if their_stack_summary.get("errorMessage") else "completed" if status != "unavailable" else "skipped",
            label="TheirStack company search",
            request_summary={
                "enabled": their_stack_summary.get("enabled"),
                "requestShape": their_stack_summary.get("requestShape"),
                "requestedPages": their_stack_summary.get("requestedPages"),
            },
            result_summary={
                "fetchedPages": their_stack_summary.get("fetchedPages"),
                "failedPages": their_stack_summary.get("failedPages"),
                "skippedPages": their_stack_summary.get("skippedPages"),
                "pageNumbersFetched": their_stack_summary.get("pageNumbersFetched"),
                "rawCompanyCount": their_stack_summary.get("rawCompanyCount"),
                "normalizedCompanyCount": their_stack_summary.get("normalizedCompanyCount"),
                "upsertedCompanyCount": their_stack_summary.get("upsertedCompanyCount"),
                "duplicateCompanyCount": their_stack_summary.get("duplicateCompanyCount"),
                "linkedCandidateCompanyCount": linked_company_count,
                "skippedCompanyCount": skipped_company_count,
                "totalCompanies": their_stack_summary.get("totalCompanies"),
                "totalResults": their_stack_summary.get("totalResults"),
                "creditsUsed": their_stack_summary.get("creditsUsed"),
                "creditsRemaining": their_stack_summary.get("creditsRemaining"),
                "skippedReason": their_stack_summary.get("skippedReason"),
                "errorType": their_stack_summary.get("errorType"),
            },
            error={"message": their_stack_summary.get("errorMessage")} if their_stack_summary.get("errorMessage") else None,
        ),
    ]
    rows.extend(
        [
            build_first_party_sync_provider_diagnostic(provider="greenhouse", sync=board_sync),
            build_first_party_sync_provider_diagnostic(provider="ashby", sync=ashby_sync),
            build_company_enrichment_provider_diagnostic(
                stage="post_sync_job_search",
                provider="jobops",
                status="completed" if job_search["job_search_attempted"] else "skipped",
                label="Post-sync job search",
                request_summary={"attempted": job_search["job_search_attempted"]},
                result_summary={
                    "syncedJobQueryCount": job_search["synced_job_query_count"],
                    "syncedJobPoolCount": job_search["synced_job_pool_count"],
                    "jobsReviewed": job_search["jobs_reviewed_count"],
                    "jobsAdded": job_search["jobs_added_count"],
                    "jobsRecommended": job_search["jobs_recommended_count"],
                    "jobsRejected": job_search["jobs_rejected_count"],
                    "unavailableReason": job_search["search_unavailable_reason"],
                },
            ),
            build_company_enrichment_provider_diagnostic(
                stage="persistence",
                provider="jobops",
                status="completed",
                label="Candidate company link/upsert",
                result_summary={
                    "linkedCompanyCount": linked_company_count,
                    "skippedCompanyCount": skipped_company_count,
                    "upsertedCompanyCount": their_stack_summary.get("upsertedCompanyCount"),
                },
            ),
        ]
    )
    return rows


def record_first_party_sync_diagnostics(
    session: Session,
    *,
    company_discovery_run_id: str | None,
    provider: str,
    sync: dict[str, Any],
) -> None:
    selected = sync["boards_selected_for_sync"]
    synced = sync["board_tokens_synced"] if provider == "greenhouse" else sync["board_urls_synced"]
    attempted = bool(sync["board_sync_attempted"])
    if sync["board_sync_failed_count"] and not sync["board_sync_completed_count"]:
        status = "failed"
    elif sync["board_sync_completed_count"] or synced:
        status = "completed"
    elif sync["sync_unavailable_reason"] == "sync_not_requested":
        status = "skipped"
    elif sync["sync_unavailable_reason"]:
        status = "unavailable"
    else:
        status = "skipped"
    record_company_discovery_provider_call(
        session,
        company_discovery_run_id=company_discovery_run_id,
        stage="first_party_sync",
        provider=provider,
        status=status,
        label=f"{provider.title()} board sync",
        request_summary={"attempted": attempted, "boardsSelected": selected},
        result_summary={
            "boardsSynced": synced,
            "completedCount": sync["board_sync_completed_count"],
            "failedCount": sync["board_sync_failed_count"],
            "rawResultCount": sync["board_sync_raw_result_count"],
            "normalizedJobCount": sync["board_sync_normalized_count"],
            "createdCount": sync["board_sync_created_count"],
            "updatedCount": sync["board_sync_updated_count"],
            "skippedFreshCount": sync["board_sync_skipped_fresh_count"],
            "unavailableReason": sync["sync_unavailable_reason"],
        },
    )


def build_first_party_sync_provider_diagnostic(*, provider: str, sync: dict[str, Any]) -> dict[str, Any]:
    selected = sync["boards_selected_for_sync"]
    synced = sync["board_tokens_synced"] if provider == "greenhouse" else sync["board_urls_synced"]
    attempted = bool(sync["board_sync_attempted"])
    if sync["board_sync_failed_count"] and not sync["board_sync_completed_count"]:
        status = "failed"
    elif sync["board_sync_completed_count"] or synced:
        status = "completed"
    elif sync["sync_unavailable_reason"] == "sync_not_requested":
        status = "skipped"
    elif sync["sync_unavailable_reason"]:
        status = "unavailable"
    else:
        status = "skipped"
    return build_company_enrichment_provider_diagnostic(
        stage="first_party_sync",
        provider=provider,
        status=status,
        label=f"{provider.title()} board sync",
        request_summary={"attempted": attempted, "boardsSelected": selected},
        result_summary={
            "boardsSynced": synced,
            "completedCount": sync["board_sync_completed_count"],
            "failedCount": sync["board_sync_failed_count"],
            "rawResultCount": sync["board_sync_raw_result_count"],
            "normalizedJobCount": sync["board_sync_normalized_count"],
            "createdCount": sync["board_sync_created_count"],
            "updatedCount": sync["board_sync_updated_count"],
            "skippedFreshCount": sync["board_sync_skipped_fresh_count"],
            "unavailableReason": sync["sync_unavailable_reason"],
        },
    )


def serialize_plan(plan: CompanyEnrichmentPlan) -> dict[str, Any]:
    return {
        "useTheirStackCompanySearch": plan.use_theirstack_company_search,
        "rationale": plan.rationale,
        "linkDiscoveredCompaniesToProfile": plan.link_discovered_companies_to_profile,
        "requireSupportedAts": plan.require_supported_ats,
        "requireGreenhouse": plan.require_greenhouse,
        "syncDiscoveredAtsBoards": plan.sync_discovered_ats_boards,
        "syncDiscoveredGreenhouseBoards": plan.sync_discovered_greenhouse_boards,
        "syncDiscoveredAshbyBoards": plan.sync_discovered_ashby_boards,
        "searchSyncedJobsAfterBoardSync": plan.search_synced_jobs_after_board_sync,
        "saveMatchingJobsToCandidateList": plan.save_matching_jobs_to_candidate_list,
        "recommendOnly": plan.recommend_only,
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


def sanitized_company_diagnostic_request_shape(value: object) -> dict[str, Any]:
    from .company_discovery import sanitize_diagnostic_request_shape

    return sanitize_diagnostic_request_shape(value)


def sanitized_theirstack_diagnostics(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    sanitized = dict(value)
    sanitized["requestShape"] = sanitized_company_diagnostic_request_shape(sanitized.get("requestShape", {}))
    return sanitized


def compact_log_preview(value: str, *, limit: int = 180) -> str:
    return re.sub(r"\s+", " ", value or "").strip()[:limit]
