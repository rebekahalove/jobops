from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal, Protocol
from urllib.parse import urlparse

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from ..db.models import CandidateCompany, CandidateSavedJob, JobPosting
from ..model_connector import ModelRequest


JobStatus = Literal["new", "saved", "archived"]
RemoteWorkMode = Literal["remote", "hybrid", "onsite", "flexible", "unknown"]
JobProvenance = Literal["provider_result", "fetched_page", "user_url", "mock"]
ProviderType = Literal["broad_search", "ats_board", "mock"]
JobSearchMode = Literal["broad", "company_specific", "followed_companies", "url"]
SkipReasonCode = Literal[
    "duplicate_for_user",
    "duplicate_global_job",
    "failed_url_verification",
    "no_live_source_provenance",
    "expired_or_closed",
    "excluded_by_user_constraints",
    "missing_required_url",
]


class ApiModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class JobDiscoveryRecord(ApiModel):
    title: str = Field(min_length=1, max_length=240)
    company_name: str = Field(
        validation_alias=AliasChoices("company_name", "companyName"),
        serialization_alias="companyName",
        min_length=1,
        max_length=240,
    )
    job_url: str = Field(
        validation_alias=AliasChoices("job_url", "jobUrl"),
        serialization_alias="jobUrl",
        min_length=1,
    )
    company_website_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("company_website_url", "companyWebsiteUrl"),
        serialization_alias="companyWebsiteUrl",
    )
    company_careers_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("company_careers_url", "companyCareersUrl"),
        serialization_alias="companyCareersUrl",
    )
    company_job_listings_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("company_job_listings_url", "companyJobListingsUrl"),
        serialization_alias="companyJobListingsUrl",
    )
    company_source_urls: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("company_source_urls", "companySourceUrls"),
        serialization_alias="companySourceUrls",
        max_length=8,
    )
    source_urls: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("source_urls", "sourceUrls"),
        serialization_alias="sourceUrls",
        max_length=8,
    )
    url_verification_summary: str | None = Field(
        default=None,
        validation_alias=AliasChoices("url_verification_summary", "urlVerificationSummary"),
        serialization_alias="urlVerificationSummary",
        max_length=500,
    )
    source: str | None = Field(default=None, validation_alias=AliasChoices("source", "provider"), max_length=120)
    location: str | None = Field(default=None, max_length=240)
    remote_work_mode: RemoteWorkMode = Field(
        default="unknown",
        validation_alias=AliasChoices("remote_work_mode", "remoteWorkMode", "work_mode", "workMode"),
        serialization_alias="remoteWorkMode",
    )
    employment_type: str | None = Field(
        default=None,
        validation_alias=AliasChoices("employment_type", "employmentType"),
        serialization_alias="employmentType",
        max_length=120,
    )
    salary_min: int | None = Field(
        default=None,
        validation_alias=AliasChoices("salary_min", "salaryMin", "compensation_min", "compensationMin"),
        serialization_alias="salaryMin",
    )
    salary_max: int | None = Field(
        default=None,
        validation_alias=AliasChoices("salary_max", "salaryMax", "compensation_max", "compensationMax"),
        serialization_alias="salaryMax",
    )
    salary_currency: str | None = Field(
        default=None,
        validation_alias=AliasChoices("salary_currency", "salaryCurrency", "currency"),
        serialization_alias="salaryCurrency",
        min_length=3,
        max_length=3,
    )
    salary_text: str | None = Field(
        default=None,
        validation_alias=AliasChoices("salary_text", "salaryText", "compensation_text", "compensationText"),
        serialization_alias="salaryText",
        max_length=500,
    )
    description_excerpt: str | None = Field(
        default=None,
        validation_alias=AliasChoices("description_excerpt", "descriptionExcerpt", "summary"),
        serialization_alias="descriptionExcerpt",
        max_length=900,
    )
    fit_summary: str | None = Field(
        default=None,
        validation_alias=AliasChoices("fit_summary", "fitSummary", "fit_reason", "fitReason"),
        serialization_alias="fitSummary",
        max_length=900,
    )
    posting_date: date | None = Field(
        default=None,
        validation_alias=AliasChoices("posting_date", "postingDate", "posted_at", "postedAt"),
        serialization_alias="postingDate",
    )

    @field_validator("job_url", mode="after")
    @classmethod
    def require_http_url(cls, value: str) -> str:
        cleaned = value.strip()
        parsed = urlparse(cleaned)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("jobUrl must be a reliable http(s) URL")
        return cleaned

    @field_validator(
        "source",
        "company_website_url",
        "company_careers_url",
        "company_job_listings_url",
        "url_verification_summary",
        "location",
        "employment_type",
        "salary_currency",
        "salary_text",
        "description_excerpt",
        "fit_summary",
        mode="after",
    )
    @classmethod
    def empty_text_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("salary_currency", mode="after")
    @classmethod
    def normalize_salary_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else None

    @field_validator("remote_work_mode", mode="before")
    @classmethod
    def normalize_remote_work_mode(cls, value: object) -> object:
        if value is None:
            return "unknown"
        if isinstance(value, str):
            stripped = value.strip().lower()
            if stripped in {"remote", "hybrid", "onsite", "flexible", "unknown"}:
                return stripped
            if stripped in {"varies", "varied", "mixed"}:
                return "unknown"
        return value

    @field_validator("company_source_urls", "source_urls")
    @classmethod
    def clean_source_url_list(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            if not isinstance(value, str):
                continue
            stripped = value.strip()
            key = stripped.casefold()
            if stripped and key not in seen:
                cleaned.append(stripped)
                seen.add(key)
        return cleaned


class SkippedJobResult(ApiModel):
    title: str | None = None
    company_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("company_name", "companyName"),
        serialization_alias="companyName",
    )
    job_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("job_url", "jobUrl"),
        serialization_alias="jobUrl",
    )
    reason_code: SkipReasonCode = Field(
        default="no_live_source_provenance",
        validation_alias=AliasChoices("reason_code", "reasonCode"),
        serialization_alias="reasonCode",
    )
    reason: str


class JobCandidateSelectionItem(ApiModel):
    candidate_id: str = Field(validation_alias=AliasChoices("candidate_id", "candidateId"), serialization_alias="candidateId")
    fit_summary: str | None = Field(
        default=None,
        validation_alias=AliasChoices("fit_summary", "fitSummary"),
        serialization_alias="fitSummary",
    )
    rank: int | None = None
    selection_reason: str | None = Field(
        default=None,
        validation_alias=AliasChoices("selection_reason", "selectionReason"),
        serialization_alias="selectionReason",
    )
    concerns: list[str] = Field(default_factory=list)


class JobCandidateSkippedNote(ApiModel):
    candidate_id: str = Field(validation_alias=AliasChoices("candidate_id", "candidateId"), serialization_alias="candidateId")
    reason: str


class JobCandidateSelectionOutput(ApiModel):
    assistant_message: str = Field(
        default="I reviewed the live provider candidates and selected the strongest matches.",
        validation_alias=AliasChoices("assistant_message", "assistantMessage"),
        serialization_alias="assistantMessage",
    )
    selected_jobs: list[JobCandidateSelectionItem] = Field(
        default_factory=list,
        validation_alias=AliasChoices("selected_jobs", "selectedJobs"),
        serialization_alias="selectedJobs",
    )
    skipped_candidate_notes: list[JobCandidateSkippedNote] = Field(
        default_factory=list,
        validation_alias=AliasChoices("skipped_candidate_notes", "skippedCandidateNotes"),
        serialization_alias="skippedCandidateNotes",
    )
    clarifying_questions: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("clarifying_questions", "clarifyingQuestions"),
        serialization_alias="clarifyingQuestions",
    )


class JobSearchPlanProviderStrategy(ApiModel):
    use_broad_search: bool = Field(
        default=True,
        validation_alias=AliasChoices("use_broad_search", "useBroadSearch"),
        serialization_alias="useBroadSearch",
    )
    use_company_boards: bool = Field(
        default=True,
        validation_alias=AliasChoices("use_company_boards", "useCompanyBoards"),
        serialization_alias="useCompanyBoards",
    )
    requested_result_goal: int = Field(
        default=20,
        validation_alias=AliasChoices("requested_result_goal", "requestedResultGoal"),
        serialization_alias="requestedResultGoal",
        ge=1,
        le=200,
    )
    max_provider_pages: int = Field(
        default=2,
        validation_alias=AliasChoices("max_provider_pages", "maxProviderPages"),
        serialization_alias="maxProviderPages",
        ge=1,
        le=10,
    )
    allow_replanning: bool = Field(
        default=True,
        validation_alias=AliasChoices("allow_replanning", "allowReplanning"),
        serialization_alias="allowReplanning",
    )


class JobSearchPlan(ApiModel):
    search_mode: JobSearchMode = Field(
        default="broad",
        validation_alias=AliasChoices("search_mode", "searchMode"),
        serialization_alias="searchMode",
    )
    role_queries: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("role_queries", "roleQueries"),
        serialization_alias="roleQueries",
        max_length=12,
    )
    company_names: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("company_names", "companyNames"),
        serialization_alias="companyNames",
        max_length=50,
    )
    locations: list[str] = Field(default_factory=list, max_length=12)
    remote_work_modes: list[RemoteWorkMode] = Field(
        default_factory=list,
        validation_alias=AliasChoices("remote_work_modes", "remoteWorkModes"),
        serialization_alias="remoteWorkModes",
        max_length=5,
    )
    employment_types: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("employment_types", "employmentTypes"),
        serialization_alias="employmentTypes",
        max_length=8,
    )
    salary_min: int | None = Field(
        default=None,
        validation_alias=AliasChoices("salary_min", "salaryMin"),
        serialization_alias="salaryMin",
        ge=0,
    )
    include_terms: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("include_terms", "includeTerms"),
        serialization_alias="includeTerms",
        max_length=20,
    )
    exclude_terms: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("exclude_terms", "excludeTerms"),
        serialization_alias="excludeTerms",
        max_length=20,
    )
    hard_constraints: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("hard_constraints", "hardConstraints"),
        serialization_alias="hardConstraints",
        max_length=20,
    )
    soft_preferences: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("soft_preferences", "softPreferences"),
        serialization_alias="softPreferences",
        max_length=20,
    )
    provider_strategy: JobSearchPlanProviderStrategy = Field(
        default_factory=JobSearchPlanProviderStrategy,
        validation_alias=AliasChoices("provider_strategy", "providerStrategy"),
        serialization_alias="providerStrategy",
    )
    rationale: str = Field(default="", max_length=900)

    @field_validator("role_queries", "company_names", "locations", "employment_types", "include_terms", "exclude_terms", "hard_constraints", "soft_preferences")
    @classmethod
    def clean_string_list(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            if not isinstance(value, str):
                continue
            stripped = " ".join(value.split()).strip(" ,.;:-")
            key = stripped.casefold()
            if stripped and key not in seen:
                cleaned.append(stripped)
                seen.add(key)
        return cleaned


class JobSearchPlannerOutput(ApiModel):
    search_plan: JobSearchPlan = Field(
        validation_alias=AliasChoices("search_plan", "searchPlan"),
        serialization_alias="searchPlan",
    )


@dataclass(frozen=True)
class JobSearchPlannerResult:
    plan: JobSearchPlan
    request: ModelRequest
    response_provider: str
    response_model: str
    response: Any | None = None
    fallback_used: bool = False
    recent_searches_used_count: int = 0


class SavedJobResponse(BaseModel):
    id: str
    candidate_profile_id: str
    job_id: str | None
    job_listing_id: str | None = None
    jobSearchRunId: str | None = None
    highlighted: bool = False
    justAdded: bool = False
    latestDiscoveryRunId: str | None = None
    title: str
    company_name: str
    job_url: str
    canonical_url: str | None
    apply_url: str | None
    source: str | None
    source_provider: str | None
    provider_type: str | None
    source_result_id: str | None
    source_query: str | None
    source_url: str | None
    source_updated_at: datetime | None
    company_website_url: str | None
    company_careers_url: str | None
    ats_provider: str | None
    ats_board_token: str | None
    provenance: str
    url_verification_status: str
    url_verification_checked_at: datetime | None
    url_verification_summary: str | None
    location: str | None
    remote_work_mode: str | None
    employment_type: str | None
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None
    salary_text: str | None
    full_description: str | None
    description_excerpt: str | None
    fit_summary: str | None
    user_notes: str | None
    status: str
    added_at: datetime
    archived_at: datetime | None
    archived_reason: str | None
    archived_by_action: str | None
    has_application: bool = False
    application_id: str | None = None
    application_status: str | None = None
    application_archived_at: datetime | None = None
    posting_date: date | None
    first_seen_at: datetime
    last_seen_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SavedJobActionResponse(BaseModel):
    ok: bool = True
    job_id: str | None
    saved_job_id: str
    job_archived: bool = False
    job_restored: bool = False
    application_id: str | None = None
    application_archived: bool = False
    application_restored: bool = False
    application_restore_skipped: bool = False
    application_archived_by_action: str | None = None
    message: str
    job: SavedJobResponse


@dataclass(frozen=True)
class JobDiscoveryRequest:
    latest_user_message: str
    candidate_profile_slug: str
    active_workspace: str | None = None
    client_context: dict[str, Any] | None = None
    router_extracted: dict[str, Any] | None = None


@dataclass(frozen=True)
class JobDiscoveryServiceResult:
    body: dict[str, Any]
    status_code: int


@dataclass(frozen=True)
class JobDiscoverySaveResult:
    saved_links: list[CandidateSavedJob]
    updated_existing_links: list[CandidateSavedJob]
    created_jobs: list[JobPosting]
    updated_jobs: list[JobPosting]
    added_companies: list[CandidateCompany]
    skipped: list[SkippedJobResult]


@dataclass(frozen=True)
class JobUrlVerificationResult:
    status: str
    checked_at: datetime
    summary: str
    final_url: str | None = None
    title: str | None = None
    company_name: str | None = None
    description_excerpt: str | None = None
    posting_date: date | None = None
    expired_or_closed: bool = False

    @property
    def verified(self) -> bool:
        return self.status == "verified"


@dataclass(frozen=True)
class LiveJobSourceResult:
    title: str
    company_name: str
    job_url: str
    source_provider: str
    provenance: JobProvenance = "provider_result"
    provider_type: ProviderType = "broad_search"
    source_result_id: str | None = None
    source_query: str | None = None
    source_url: str | None = None
    apply_url: str | None = None
    location: str | None = None
    remote_work_mode: str | None = None
    employment_type: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None
    salary_text: str | None = None
    full_description: str | None = None
    description_excerpt: str | None = None
    posting_date: date | None = None
    source_updated_at: datetime | None = None
    company_website_url: str | None = None
    company_careers_url: str | None = None
    company_job_listings_url: str | None = None
    ats_provider: str | None = None
    ats_board_token: str | None = None
    fit_summary: str | None = None
    source_urls: tuple[str, ...] = ()
    raw_metadata: dict[str, Any] | None = None
    url_verification_status: str = "provider_unverified"
    url_verification_checked_at: datetime | None = None
    url_verification_summary: str | None = None


@dataclass(frozen=True)
class JobSearchRequest:
    latest_user_message: str
    search_queries: list[str]
    results_per_provider: int
    current_saved_companies: list[dict[str, Any]]
    target_context: dict[str, Any]
    private_profile_context: dict[str, Any]
    user_constraints: list[str]
    search_plan: JobSearchPlan | None = None
    company_names: list[str] | None = None
    locations: list[str] | None = None
    max_provider_pages: int = 1


@dataclass(frozen=True)
class ProviderDiagnostic:
    provider_name: str
    provider_type: ProviderType | str
    configured: bool
    attempted: bool
    result_count: int = 0
    raw_result_count: int | None = None
    error: str | None = None
    query: str | None = None
    company_name: str | None = None
    location: str | None = None
    page: int | None = None
    pages_attempted: int | None = None
    total_matches: int | None = None
    normalized_result_count: int | None = None
    deduped_result_count: int | None = None
    candidate_count_after_filters: int | None = None
    request_criteria: dict[str, Any] | None = None
    board_token: str | None = None
    search_mode: str | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "providerName": self.provider_name,
            "providerType": self.provider_type,
            "configured": self.configured,
            "attempted": self.attempted,
            "resultCount": self.result_count,
            "rawResultCount": self.raw_result_count,
            "error": self.error,
            "query": self.query,
            "companyName": self.company_name,
            "location": self.location,
            "page": self.page,
            "pagesAttempted": self.pages_attempted,
            "totalMatches": self.total_matches,
            "normalizedResultCount": self.normalized_result_count,
            "dedupedResultCount": self.deduped_result_count,
            "candidateCountAfterFilters": self.candidate_count_after_filters,
            "requestCriteria": self.request_criteria,
            "boardToken": self.board_token,
            "searchMode": self.search_mode,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ProviderSearchOutcome:
    results: list[LiveJobSourceResult]
    diagnostics: list[ProviderDiagnostic]
    errors: list[str]


@dataclass(frozen=True)
class CandidatePoolEntry:
    candidate_id: str
    result: LiveJobSourceResult
    rough_score: int = 0
    flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class CandidatePoolBuildResult:
    entries: list[CandidatePoolEntry]
    skipped: list[SkippedJobResult]
    count_after_provider_normalization: int
    count_after_dedupe: int
    count_after_hard_exclusion_filter: int
    count_after_diversity_cap: int
    trimmed_by_company_cap_count: int
    trimmed_by_provider_cap_count: int


@dataclass(frozen=True)
class JobCandidateSelectionResult:
    output: JobCandidateSelectionOutput
    selected_entries: list[CandidatePoolEntry]
    invalid_candidate_ids: list[str]
    response_provider: str
    response_model: str
    request: ModelRequest
    response: Any | None


class JobDiscoveryProvider(Protocol):
    provider_name: str
    provider_type: ProviderType

    def is_configured(self, settings) -> bool:
        ...

    def search(self, request: JobSearchRequest, settings) -> ProviderSearchOutcome:
        ...


class JobProviderConfigurationError(Exception):
    pass


class JobProviderRuntimeError(Exception):
    pass
