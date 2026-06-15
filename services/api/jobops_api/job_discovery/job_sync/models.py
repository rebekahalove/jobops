from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal


ProviderType = Literal["broad_search", "ats_board", "mock"]
SyncKind = Literal["company_board", "broad_search", "direct_url"]


@dataclass(frozen=True)
class JobSyncLocation:
    display_location: str | None
    provider_country: str
    provider_where: str | None
    target_country: str | None = None
    target_location_kind: str | None = None
    location_city: str | None = None
    location_region: str | None = None
    location_country: str | None = None
    location_metro: str | None = None
    location_confidence: str | None = None
    normalized_key: str | None = None
    target_id: str | None = None
    provider_mapping_id: str | None = None
    provider_mapping_confidence: str | None = None
    provider_mapping_status: str | None = None


@dataclass(frozen=True)
class BroadJobSyncSignature:
    provider_country: str
    location_key: str
    query_text: str
    sync_key: str


@dataclass(frozen=True)
class JobSyncRequest:
    sync_key: str
    provider_name: str
    provider_type: ProviderType | str
    sync_kind: SyncKind | str
    job_sync_signature_id: str | None = None
    company_id: str | None = None
    company_name: str | None = None
    ats_provider: str | None = None
    ats_board_token: str | None = None
    provider_country: str | None = None
    target_country: str | None = None
    target_location_kind: str | None = None
    display_location: str | None = None
    provider_where: str | None = None
    query_text: str | None = None
    query_kind: str | None = None
    criteria_json: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedJobListing:
    title: str
    company_name: str
    job_location_target_id: str | None = None
    company_id: str | None = None
    canonical_url: str | None = None
    apply_url: str | None = None
    source_url: str | None = None
    location_raw: str | None = None
    location_display: str | None = None
    location_city: str | None = None
    location_region: str | None = None
    location_country: str | None = None
    location_metro: str | None = None
    location_confidence: str | None = None
    remote_work_mode: str | None = None
    employment_type: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None
    salary_text: str | None = None
    description_excerpt: str | None = None
    full_description: str | None = None
    posting_date: date | None = None
    source_updated_at: datetime | None = None
    source_status: str | None = None


@dataclass(frozen=True)
class JobListingSourceRecord:
    source_provider: str
    provider_type: ProviderType | str
    provider_job_id: str | None = None
    source_result_id: str | None = None
    ats_provider: str | None = None
    ats_board_token: str | None = None
    source_url: str | None = None
    apply_url: str | None = None
    canonical_url: str | None = None
    source_query: str | None = None
    source_location: str | None = None
    source_country: str | None = None
    raw_location: str | None = None
    raw_metadata_json: dict[str, Any] = field(default_factory=dict)
    application_fields_json: dict[str, Any] | None = None
    application_requirements_json: dict[str, Any] | None = None
    pay_transparency_json: dict[str, Any] | None = None
    source_updated_at: datetime | None = None
    source_status: str | None = None


@dataclass(frozen=True)
class JobSyncPlan:
    requests: tuple[JobSyncRequest, ...]


@dataclass(frozen=True)
class JobSyncResult:
    request: JobSyncRequest
    status: str = "completed"
    raw_result_count: int = 0
    normalized_count: int = 0
    created_count: int = 0
    updated_count: int = 0
    closed_count: int = 0
    failed_normalization_count: int = 0
    error: str | None = None
    diagnostics_json: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class JobListingUpsertResult:
    job_listing_id: str
    job_listing_source_id: str
    created: bool
    updated: bool
