from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.orm import Session

from ....provider_utils import clean_text_value
from ....providers.greenhouse import canonical_greenhouse_jobs_api_url, normalize_greenhouse_board_token
from ...base import BaseJobSyncProvider
from ...models import JobListingSourceRecord, JobSyncPlan, JobSyncRequest, JobSyncResult, NormalizedJobListing
from ...service import (
    build_greenhouse_sync_key,
    is_sync_fresh,
    latest_completed_sync_at,
    record_job_sync_run,
    upsert_job_listing_from_provider_record,
)
from .client import GreenhouseJobBoardClient
from .mapper import merge_greenhouse_job_payloads, normalize_greenhouse_job_record
from .models import GreenhouseBoardSyncTarget, GreenhouseDetailFetchResult, GreenhouseListJobsResult
from .stale import mark_missing_greenhouse_board_jobs_closed


class GreenhouseJobSyncProvider(BaseJobSyncProvider):
    provider_name = "greenhouse"
    provider_type = "ats_board"

    def __init__(
        self,
        *,
        max_detail_requests: int | None = None,
        client: GreenhouseJobBoardClient | None = None,
    ) -> None:
        self.client = client or GreenhouseJobBoardClient(max_detail_requests=max_detail_requests)
        self.latest_list_result = GreenhouseListJobsResult(jobs=(), provider_job_ids=(), valid=False)

    @property
    def max_detail_requests(self) -> int | None:
        return self.client.max_detail_requests

    @property
    def detail_requests_attempted(self) -> int:
        return self.client.detail_stats.attempted

    @property
    def detail_requests_succeeded(self) -> int:
        return self.client.detail_stats.succeeded

    @property
    def detail_requests_failed(self) -> int:
        return self.client.detail_stats.failed

    @property
    def detail_requests_skipped(self) -> int:
        return self.client.detail_stats.skipped_by_guardrail

    def build_sync_plan(self, board_tokens: Iterable[str | GreenhouseBoardSyncTarget]) -> JobSyncPlan:
        requests: list[JobSyncRequest] = []
        for target in dedupe_greenhouse_board_sync_targets(board_tokens):
            board_token = target.board_token
            if not board_token:
                continue
            api_url = canonical_greenhouse_jobs_api_url(board_token)
            retrieve_url_template = f"{api_url}/{{job_id}}"
            requests.append(
                JobSyncRequest(
                    sync_key=build_greenhouse_sync_key(board_token),
                    provider_name=self.provider_name,
                    provider_type=self.provider_type,
                    sync_kind="company_board",
                    company_id=target.company_id,
                    company_name=target.company_name,
                    ats_provider="greenhouse",
                    ats_board_token=board_token,
                    criteria_json={
                        "boardToken": board_token,
                        "targetSource": target.source,
                        "apiUrl": api_url,
                        "content": True,
                        "retrieveJobApiUrlTemplate": retrieve_url_template,
                        "retrieveJobQuestions": True,
                        "retrieveJobPayTransparency": True,
                        "maxDetailRequests": self.max_detail_requests,
                        "syncKey": build_greenhouse_sync_key(board_token),
                    },
                )
            )
        return JobSyncPlan(requests=tuple(requests))

    def refresh_diagnostics(self, request: JobSyncRequest) -> dict[str, object]:
        return self.client.diagnostics_json()

    def fetch_provider_records(self, request: JobSyncRequest) -> Iterable[object]:
        if not request.ats_board_token:
            raise ValueError("Greenhouse Job Sync requests require ats_board_token.")
        self.client.reset()
        self.latest_list_result = self.client.list_board_jobs(request.ats_board_token)
        if not self.latest_list_result.valid:
            raise ValueError(self.latest_list_result.error or "Greenhouse list-jobs response was malformed.")
        return tuple(self.fetch_and_merge_job_detail(request, raw_job) for raw_job in self.latest_list_result.jobs)

    def fetch_and_merge_job_detail(self, request: JobSyncRequest, raw_job: object) -> object:
        detail_result = self.client.retrieve_job_detail(board_token=request.ats_board_token or "", raw_job=raw_job)
        if isinstance(detail_result, GreenhouseDetailFetchResult):
            return merge_greenhouse_job_payloads(detail_result)
        return detail_result

    def reset_detail_counts(self) -> None:
        self.client.reset()
        self.latest_list_result = GreenhouseListJobsResult(jobs=(), provider_job_ids=(), valid=False)

    def refresh_inventory(
        self,
        session: Session,
        request: JobSyncRequest,
        *,
        freshness_hours: int = 24,
        force: bool = False,
    ) -> JobSyncResult:
        if not force and is_sync_fresh(session, request.sync_key, freshness_hours=freshness_hours):
            latest_completed = latest_completed_sync_at(session, request.sync_key)
            sync_result = JobSyncResult(
                request=request,
                status="skipped_fresh",
                diagnostics_json={
                    "skipReason": "fresh",
                    "freshnessHours": freshness_hours,
                    "latestCompletedAt": latest_completed.isoformat() if latest_completed else None,
                },
            )
            record_job_sync_run(session, sync_result)
            return sync_result

        try:
            raw_records = tuple(self.fetch_provider_records(request))
        except Exception as error:
            sync_result = JobSyncResult(
                request=request,
                status="failed",
                error=str(error),
                diagnostics_json={
                    **self.refresh_diagnostics(request),
                    "listJobsResponseValid": False,
                    "listJobsError": str(error),
                },
            )
            record_job_sync_run(session, sync_result)
            return sync_result

        created_count = 0
        updated_count = 0
        failed_normalization_count = 0
        normalized_count = 0

        for raw in raw_records:
            normalized = self.normalize_provider_record(raw, request, session=session)
            if normalized is None:
                failed_normalization_count += 1
                continue
            listing, source = normalized
            result = upsert_job_listing_from_provider_record(session, listing=listing, source=source)
            normalized_count += 1
            created_count += int(result.created)
            updated_count += int(result.updated)

        closed_count = mark_missing_greenhouse_board_jobs_closed(
            session,
            board_token=request.ats_board_token,
            current_provider_job_ids=self.latest_list_result.provider_job_ids,
            list_response_valid=self.latest_list_result.valid,
        )
        sync_result = JobSyncResult(
            request=request,
            raw_result_count=len(raw_records),
            normalized_count=normalized_count,
            created_count=created_count,
            updated_count=updated_count,
            closed_count=closed_count,
            failed_normalization_count=failed_normalization_count,
            diagnostics_json={
                **self.refresh_diagnostics(request),
                "listJobsResponseValid": self.latest_list_result.valid,
            },
        )
        record_job_sync_run(session, sync_result)
        return sync_result

    def normalize_provider_record(
        self,
        raw: object,
        request: JobSyncRequest,
        *,
        session: Session,
    ) -> tuple[NormalizedJobListing, JobListingSourceRecord] | None:
        return normalize_greenhouse_job_record(raw, request, session=session)


def normalize_greenhouse_board_sync_target(raw_target: str | GreenhouseBoardSyncTarget) -> GreenhouseBoardSyncTarget:
    if isinstance(raw_target, GreenhouseBoardSyncTarget):
        return GreenhouseBoardSyncTarget(
            board_token=normalize_greenhouse_board_token(raw_target.board_token),
            company_id=raw_target.company_id,
            company_name=clean_text_value(raw_target.company_name),
            source=raw_target.source,
        )
    return GreenhouseBoardSyncTarget(board_token=normalize_greenhouse_board_token(raw_target), source="bare_board_token")


def dedupe_greenhouse_board_sync_targets(
    targets: Iterable[str | GreenhouseBoardSyncTarget],
) -> tuple[GreenhouseBoardSyncTarget, ...]:
    deduped: list[GreenhouseBoardSyncTarget] = []
    seen_index_by_key: dict[str, int] = {}
    for raw_target in targets:
        target = normalize_greenhouse_board_sync_target(raw_target)
        token = target.board_token
        key = token.casefold()
        if not token:
            continue
        if key in seen_index_by_key:
            existing_index = seen_index_by_key[key]
            if greenhouse_target_metadata_score(target) > greenhouse_target_metadata_score(deduped[existing_index]):
                deduped[existing_index] = target
            continue
        seen_index_by_key[key] = len(deduped)
        deduped.append(target)
    return tuple(deduped)


def greenhouse_target_metadata_score(target: GreenhouseBoardSyncTarget) -> int:
    return int(bool(target.company_name)) + (2 * int(bool(target.company_id)))
