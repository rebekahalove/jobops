from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ....company_canonicalization import ensure_candidate_company_link, upsert_canonical_company
from ....db.models import CandidateSavedJob, Company, JobListing
from ...greenhouse_utils import canonical_greenhouse_jobs_api_url
from ..statuses import HIDDEN_JOB_STATUSES
from .models import DirectUrlCompanyResolution, DirectUrlSavedJobWriteResult


class GreenhouseDirectUrlCompanyResolver:
    def __init__(self, session: Session) -> None:
        self.session = session

    def resolve(
        self,
        *,
        candidate_profile_id: str,
        board_token: str,
        direct_url: str,
    ) -> DirectUrlCompanyResolution:
        fallback_name = board_token.replace("-", " ").replace("_", " ").title()
        jobs_api_url = canonical_greenhouse_jobs_api_url(board_token)
        company = upsert_canonical_company(
            self.session,
            name=fallback_name,
            job_listings_url=jobs_api_url,
            source_urls=[direct_url, jobs_api_url],
            source_summary="Created or refreshed from direct Greenhouse job URL ingestion.",
            data_confidence="low",
            greenhouse_board_token=board_token,
            last_seen_at=datetime.now(UTC),
        )
        link_result = ensure_candidate_company_link(
            self.session,
            candidate_profile_id=candidate_profile_id,
            company=company,
            review_status="new",
            derivation_status="direct_url",
            fit_reason="Added through a direct Greenhouse job URL.",
            provider_grounding_metadata={
                "provider": "greenhouse",
                "boardToken": board_token,
                "directUrl": direct_url,
                "jobsApiUrl": jobs_api_url,
            },
            discovered_by="direct_job_url",
            personal_source_urls=[direct_url],
        )
        return DirectUrlCompanyResolution(
            company=company,
            candidate_company=link_result.link,
            created_candidate_company=link_result.created_link,
        )


class DirectUrlSavedJobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save_or_refresh(
        self,
        *,
        candidate_profile_id: str,
        job_listing_id: str,
        job_search_run_id: str,
        source_command: str,
        diagnostics: dict[str, Any],
    ) -> DirectUrlSavedJobWriteResult:
        saved_job = self.session.scalar(
            select(CandidateSavedJob)
            .where(
                CandidateSavedJob.candidate_profile_id == candidate_profile_id,
                CandidateSavedJob.job_listing_id == job_listing_id,
            )
            .options(selectinload(CandidateSavedJob.job_listing).selectinload(JobListing.sources))
        )
        created = saved_job is None
        if saved_job is None:
            saved_job = CandidateSavedJob(
                job_listing_id=job_listing_id,
                candidate_profile_id=candidate_profile_id,
                job_search_run_id=job_search_run_id,
                status="new",
                source_command=source_command,
                discovery_metadata={"directUrlIngestion": diagnostics},
            )
            self.session.add(saved_job)
        else:
            if saved_job.archived_at is not None or saved_job.status in HIDDEN_JOB_STATUSES:
                saved_job.status = "new"
            saved_job.job_search_run_id = job_search_run_id
            saved_job.source_command = source_command
            saved_job.archived_at = None
            saved_job.archived_reason = None
            saved_job.archived_by_action = None
            saved_job.discovery_metadata = {
                **(saved_job.discovery_metadata or {}),
                "directUrlIngestion": diagnostics,
            }
            self.session.add(saved_job)
        self.session.flush()
        self.session.refresh(saved_job, attribute_names=["job_listing"])
        return DirectUrlSavedJobWriteResult(saved_job=saved_job, created=created, refreshed=not created)
