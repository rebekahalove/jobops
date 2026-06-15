from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel


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
    hasApplicationFields: bool = False
    requiredFieldCount: int | None = None
    shortAnswerQuestionCount: int | None = None
    requiresResume: bool | None = None
    requiresCoverLetter: bool | None = None
    requiresPortfolioUrl: bool | None = None
    requiresLinkedIn: bool | None = None
    requiresWebsite: bool | None = None
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
