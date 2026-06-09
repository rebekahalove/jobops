from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal


ProviderType = Literal["broad_search", "ats_board", "mock"]
SyncKind = Literal["company_board", "broad_search"]


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


def normalize_job_sync_location(value: str | None, *, default_provider_country: str = "us") -> JobSyncLocation:
    cleaned = " ".join((value or "").replace(",", ", ").split()).strip(" ,")
    key = cleaned.casefold()
    default_country = normalize_provider_country(default_provider_country) or "us"
    if not cleaned:
        return JobSyncLocation(display_location=None, provider_country=default_country, provider_where=None)
    if key in {"remote us", "remote usa", "remote united states", "united states remote", "us remote"}:
        return JobSyncLocation(
            display_location="Remote US",
            provider_country="us",
            provider_where=None,
            target_country="United States",
            target_location_kind="remote_country",
            location_country="US",
            location_confidence="high",
        )
    if key in {"remote uk", "remote gb", "remote united kingdom", "united kingdom remote", "uk remote"}:
        return JobSyncLocation(
            display_location="Remote UK",
            provider_country="gb",
            provider_where=None,
            target_country="United Kingdom",
            target_location_kind="remote_country",
            location_country="GB",
            location_confidence="high",
        )
    if key in {"louisville ky", "louisville, ky", "louisville kentucky", "louisville, kentucky"}:
        return JobSyncLocation(
            display_location="Louisville, KY",
            provider_country="us",
            provider_where="Louisville, Kentucky",
            target_country="United States",
            target_location_kind="city",
            location_city="Louisville",
            location_region="KY",
            location_country="US",
            location_metro="Louisville",
            location_confidence="high",
        )
    if key in {"london uk", "london, uk", "london gb", "london, gb", "london united kingdom", "london, united kingdom"}:
        return JobSyncLocation(
            display_location="London, UK",
            provider_country="gb",
            provider_where="London",
            target_country="United Kingdom",
            target_location_kind="city",
            location_city="London",
            location_country="GB",
            location_metro="London",
            location_confidence="high",
        )
    return JobSyncLocation(
        display_location=cleaned,
        provider_country=default_country,
        provider_where=cleaned,
        target_location_kind="raw",
        location_confidence="low",
    )


def normalize_provider_country(value: str | None) -> str | None:
    cleaned = (value or "").strip().casefold()
    if cleaned in {"uk", "gb", "gbr", "united kingdom", "great britain"}:
        return "gb"
    if cleaned in {"us", "usa", "united states", "united states of america"}:
        return "us"
    return cleaned or None
