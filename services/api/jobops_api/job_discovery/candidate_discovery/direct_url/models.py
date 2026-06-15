from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from sqlalchemy.orm import Session

from ....db.models import CandidateCompany, CandidateProfile, CandidateSavedJob, Company
from ....settings import Settings
from ...job_sync.models import JobSyncResult


DirectUrlIngestionStatus = Literal["added", "refreshed", "unsupported", "failed"]


@dataclass(frozen=True)
class DirectJobUrlIngestionContext:
    session: Session
    settings: Settings
    candidate_profile: CandidateProfile
    current_saved_companies: list[dict[str, Any]]
    latest_user_message: str
    job_search_run_id: str


@dataclass(frozen=True)
class DirectJobUrlIngestionResult:
    status: DirectUrlIngestionStatus
    provider: str
    url: str
    job_listing_id: str | None = None
    job_listing_source_id: str | None = None
    saved_job_id: str | None = None
    company_id: str | None = None
    candidate_company_id: str | None = None
    created_listing: bool = False
    updated_listing: bool = False
    created_saved_job: bool = False
    refreshed_saved_job: bool = False
    saved_job: CandidateSavedJob | None = None
    sync_result: JobSyncResult | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True)
class DirectUrlCompanyResolution:
    company: Company
    candidate_company: CandidateCompany
    created_candidate_company: bool


@dataclass(frozen=True)
class DirectUrlSavedJobWriteResult:
    saved_job: CandidateSavedJob
    created: bool
    refreshed: bool


class DirectJobUrlProvider(Protocol):
    provider_name: str

    def can_handle(self, url: str) -> bool:
        ...

    def ingest(self, url: str, context: DirectJobUrlIngestionContext) -> DirectJobUrlIngestionResult:
        ...
