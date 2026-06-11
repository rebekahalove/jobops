from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal


JobScope = Literal["new_to_candidate", "candidate_jobs_list", "all_accessible_jobs"]


@dataclass(frozen=True)
class DbJobSearchQuery:
    label: str = "Synced job inventory search"
    active_only: bool = True
    title_terms_any: tuple[str, ...] = ()
    title_terms_all: tuple[str, ...] = ()
    title_terms_exclude: tuple[str, ...] = ()
    description_terms_any: tuple[str, ...] = ()
    description_terms_all: tuple[str, ...] = ()
    description_terms_exclude: tuple[str, ...] = ()
    company_ids_any: tuple[str, ...] = ()
    company_names_any: tuple[str, ...] = ()
    company_names_exclude: tuple[str, ...] = ()
    source_providers_any: tuple[str, ...] = ()
    ats_board_tokens_any: tuple[str, ...] = ()
    location_target_ids_any: tuple[str, ...] = ()
    location_countries_any: tuple[str, ...] = ()
    location_regions_any: tuple[str, ...] = ()
    location_cities_any: tuple[str, ...] = ()
    location_metros_any: tuple[str, ...] = ()
    location_display_terms_any: tuple[str, ...] = ()
    remote_work_modes_any: tuple[str, ...] = ()
    employment_types_any: tuple[str, ...] = ()
    salary_currency: str | None = None
    salary_min_at_least: int | None = None
    posting_date_after: date | None = None
    source_updated_after: datetime | None = None
    last_seen_after: datetime | None = None
    freshness_days: int | None = 90
    source_statuses_any: tuple[str, ...] = ("active",)
    include_model_rejected: bool = False
    limit: int = 300
    order_by: str = "last_seen_at_desc"


@dataclass(frozen=True)
class DbJobSearchPlan:
    job_scope: JobScope = "new_to_candidate"
    queries: tuple[DbJobSearchQuery, ...] = (DbJobSearchQuery(),)
    min_job_pool_size: int = 40
    max_job_pool_size: int = 300
    max_jobs_for_model_review: int = 80
    proposed_adzuna_signatures: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class JobPoolEntry:
    job_listing_id: str
    title: str
    company_name: str
    location_display: str | None
    remote_work_mode: str | None
    employment_type: str | None
    salary_text: str | None
    description_excerpt: str | None
    source_providers: tuple[str, ...] = ()
    relevance_reason: str | None = None


@dataclass(frozen=True)
class SelectedJobDecision:
    job_listing_id: str
    rationale: str | None = None
    match_highlights: tuple[str, ...] = ()


@dataclass(frozen=True)
class RejectedJobDecision:
    job_listing_id: str
    reason_codes: tuple[str, ...] = ("other",)
    explanation: str | None = None


@dataclass(frozen=True)
class JobReviewResult:
    user_visible_summary: str
    selected_jobs: tuple[SelectedJobDecision, ...] = ()
    rejected_jobs: tuple[RejectedJobDecision, ...] = ()
    criteria_adjustment_suggestion: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateDiscoveryResult:
    assistant_message: str
    job_search_run_id: str
    search_plan: DbJobSearchPlan
    selected_candidate_jobs: tuple[Any, ...]
    updated_candidate_jobs: tuple[Any, ...]
    rejected_candidate_jobs: tuple[Any, ...]
    job_sync_results: tuple[Any, ...]
    query_counts: tuple[tuple[str, int], ...]
    unique_job_pool_count: int
    jobs_reviewed_count: int
    added_count: int
    updated_count: int
    rejected_count: int
    diagnostics: dict[str, Any]
