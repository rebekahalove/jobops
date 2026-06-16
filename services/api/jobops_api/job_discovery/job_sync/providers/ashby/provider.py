from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.orm import Session

from ....ashby_utils import ashby_posting_api_url, canonical_ashby_board_url, normalize_ashby_org_slug, parse_ashby_job_board_url
from ....provider_utils import clean_text_value
from ...base import BaseJobSyncProvider
from ...models import JobListingSourceRecord, JobSyncPlan, JobSyncRequest, JobSyncResult, NormalizedJobListing
from ...service import is_sync_fresh, latest_completed_sync_at, record_job_sync_run, upsert_job_listing_from_provider_record
from .client import AshbyJobBoardClient
from .mapper import normalize_ashby_job_record
from .models import AshbyBoardSyncTarget, AshbyListJobsResult


class AshbyJobSyncProvider(BaseJobSyncProvider):
    provider_name = "ashby"
    provider_type = "ats_board"

    def __init__(self, *, client: AshbyJobBoardClient | None = None) -> None:
        self.client = client or AshbyJobBoardClient()
        self.latest_list_result = AshbyListJobsResult(jobs=(), provider_job_ids=(), valid=False)

    def build_sync_plan(self, board_urls: Iterable[str | AshbyBoardSyncTarget]) -> JobSyncPlan:
        requests: list[JobSyncRequest] = []
        for target in dedupe_ashby_board_sync_targets(board_urls):
            org_slug = target.org_slug
            if not org_slug:
                continue
            board_url = canonical_ashby_board_url(org_slug)
            requests.append(
                JobSyncRequest(
                    sync_key=build_ashby_sync_key(org_slug),
                    provider_name=self.provider_name,
                    provider_type=self.provider_type,
                    sync_kind="company_board",
                    company_id=target.company_id,
                    company_name=target.company_name,
                    ats_provider="ashby",
                    ats_board_token=org_slug,
                    criteria_json={
                        "orgSlug": org_slug,
                        "boardUrl": board_url,
                        "targetSource": target.source,
                        "listJobsUrl": ashby_posting_api_url(org_slug),
                        "syncKey": build_ashby_sync_key(org_slug),
                    },
                )
            )
        return JobSyncPlan(requests=tuple(requests))

    def refresh_diagnostics(self, request: JobSyncRequest) -> dict[str, object]:
        org_slug = request.ats_board_token or ""
        return {
            **self.client.diagnostics_json(org_slug=org_slug),
            "listJobsRawCount": len(self.latest_list_result.jobs),
            "listJobsProviderJobIdCount": len(self.latest_list_result.provider_job_ids),
        }

    def fetch_provider_records(self, request: JobSyncRequest) -> Iterable[object]:
        if not request.ats_board_token:
            raise ValueError("Ashby Job Sync requests require ats_board_token.")
        self.latest_list_result = self.client.list_board_jobs(request.ats_board_token)
        if not self.latest_list_result.valid:
            raise ValueError(self.latest_list_result.error or "Ashby list-jobs response was malformed.")
        return self.latest_list_result.jobs

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

        sync_result = JobSyncResult(
            request=request,
            raw_result_count=len(raw_records),
            normalized_count=normalized_count,
            created_count=created_count,
            updated_count=updated_count,
            failed_normalization_count=failed_normalization_count,
            diagnostics_json=self.refresh_diagnostics(request),
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
        return normalize_ashby_job_record(raw, request, session=session)


def build_ashby_sync_key(org_slug: str) -> str:
    return f"ashby:board:{normalize_ashby_org_slug(org_slug).casefold()}"


def normalize_ashby_board_sync_target(raw_target: str | AshbyBoardSyncTarget) -> AshbyBoardSyncTarget:
    if isinstance(raw_target, AshbyBoardSyncTarget):
        parsed = parse_ashby_job_board_url(raw_target.board_url) if raw_target.board_url else None
        org_slug = normalize_ashby_org_slug(raw_target.org_slug or (parsed.org_slug if parsed else ""))
        board_url = canonical_ashby_board_url(org_slug) if org_slug else ""
        return AshbyBoardSyncTarget(
            board_url=board_url,
            org_slug=org_slug,
            company_id=raw_target.company_id,
            company_name=clean_text_value(raw_target.company_name),
            source=raw_target.source,
        )
    parsed = parse_ashby_job_board_url(raw_target)
    org_slug = parsed.org_slug if parsed else normalize_ashby_org_slug(raw_target)
    return AshbyBoardSyncTarget(
        board_url=canonical_ashby_board_url(org_slug) if org_slug else "",
        org_slug=org_slug,
        source="bare_board_url",
    )


def dedupe_ashby_board_sync_targets(
    targets: Iterable[str | AshbyBoardSyncTarget],
) -> tuple[AshbyBoardSyncTarget, ...]:
    deduped: list[AshbyBoardSyncTarget] = []
    seen_index_by_key: dict[str, int] = {}
    for raw_target in targets:
        target = normalize_ashby_board_sync_target(raw_target)
        key = (target.org_slug or "").casefold()
        if not key:
            continue
        if key in seen_index_by_key:
            existing_index = seen_index_by_key[key]
            if ashby_target_metadata_score(target) > ashby_target_metadata_score(deduped[existing_index]):
                deduped[existing_index] = target
            continue
        seen_index_by_key[key] = len(deduped)
        deduped.append(target)
    return tuple(deduped)


def ashby_target_metadata_score(target: AshbyBoardSyncTarget) -> int:
    return int(bool(target.company_name)) + (2 * int(bool(target.company_id)))
