from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from sqlalchemy.orm import Session

from .models import JobListingSourceRecord, JobSyncPlan, JobSyncRequest, JobSyncResult, NormalizedJobListing
from .service import is_sync_fresh, record_job_sync_run, upsert_job_listing_from_provider_record


class BaseJobSyncProvider(ABC):
    provider_name: str
    provider_type: str

    @abstractmethod
    def build_sync_plan(self, *args, **kwargs) -> JobSyncPlan:
        """Build provider API requests without executing them."""

    def is_request_fresh(self, session: Session, request: JobSyncRequest, *, freshness_hours: int = 24) -> bool:
        return is_sync_fresh(session, request.sync_key, freshness_hours=freshness_hours)

    @abstractmethod
    def fetch_provider_records(self, request: JobSyncRequest) -> Iterable[object]:
        """Fetch raw provider records for a sync request."""

    @abstractmethod
    def normalize_provider_record(
        self,
        raw: object,
        request: JobSyncRequest,
    ) -> tuple[NormalizedJobListing, JobListingSourceRecord] | None:
        """Convert a provider record into listing and provenance records."""

    def refresh_inventory(
        self,
        session: Session,
        request: JobSyncRequest,
        *,
        freshness_hours: int = 24,
    ) -> JobSyncResult:
        if self.is_request_fresh(session, request, freshness_hours=freshness_hours):
            return JobSyncResult(request=request)

        raw_records = list(self.fetch_provider_records(request))
        created_count = 0
        updated_count = 0
        failed_normalization_count = 0
        normalized_count = 0

        for raw in raw_records:
            normalized = self.normalize_provider_record(raw, request)
            if normalized is None:
                failed_normalization_count += 1
                continue
            listing, source = normalized
            result = upsert_job_listing_from_provider_record(session, listing=listing, source=source)
            normalized_count += 1
            created_count += int(result.created)
            updated_count += int(result.updated)

        sync_result = JobSyncResult(
            request=request,
            raw_result_count=len(raw_records),
            normalized_count=normalized_count,
            created_count=created_count,
            updated_count=updated_count,
            failed_normalization_count=failed_normalization_count,
        )
        record_job_sync_run(session, sync_result)
        return sync_result
