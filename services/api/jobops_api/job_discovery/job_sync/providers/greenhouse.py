from __future__ import annotations

import urllib.error
from collections.abc import Iterable

from sqlalchemy.orm import Session

from ...provider_utils import clean_text_value, fetch_json, html_to_text, infer_remote_mode, nested_get, parse_datetime_value
from ...providers.greenhouse import canonical_greenhouse_jobs_api_url, normalize_greenhouse_board_token
from ..base import BaseJobSyncProvider
from ..location_resolver import resolve_or_create_job_location_from_provider_payload
from ..models import JobListingSourceRecord, JobSyncPlan, JobSyncRequest, NormalizedJobListing
from ..service import build_greenhouse_sync_key


class GreenhouseJobSyncProvider(BaseJobSyncProvider):
    provider_name = "greenhouse"
    provider_type = "ats_board"
    detail_request_params = {"questions": "true", "pay_transparency": "true"}

    def __init__(self, *, max_detail_requests: int | None = None) -> None:
        self.max_detail_requests = max_detail_requests
        self.detail_requests_attempted = 0
        self.detail_requests_succeeded = 0
        self.detail_requests_failed = 0
        self.detail_requests_skipped = 0

    def build_sync_plan(self, board_tokens: Iterable[str]) -> JobSyncPlan:
        requests: list[JobSyncRequest] = []
        for raw_token in board_tokens:
            board_token = normalize_greenhouse_board_token(raw_token)
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
                    ats_provider="greenhouse",
                    ats_board_token=board_token,
                    criteria_json={
                        "boardToken": board_token,
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
        return {
            "detailRequestsAttempted": self.detail_requests_attempted,
            "detailRequestsSucceeded": self.detail_requests_succeeded,
            "detailRequestsFailed": self.detail_requests_failed,
            "detailRequestsSkipped": self.detail_requests_skipped,
        }

    def fetch_provider_records(self, request: JobSyncRequest) -> Iterable[object]:
        if not request.ats_board_token:
            raise ValueError("Greenhouse Job Sync requests require ats_board_token.")
        self.reset_detail_counts()
        url = canonical_greenhouse_jobs_api_url(request.ats_board_token)
        try:
            payload = fetch_json(url, params={"content": "true"})
        except urllib.error.HTTPError:
            raise
        raw_jobs = payload.get("jobs") if isinstance(payload, dict) else []
        if not isinstance(raw_jobs, list):
            return []
        return [self.fetch_job_detail(request, raw_job) for raw_job in raw_jobs]

    def fetch_job_detail(self, request: JobSyncRequest, raw_job: object) -> object:
        if not isinstance(raw_job, dict) or not request.ats_board_token:
            return raw_job
        provider_job_id = clean_text_value(raw_job.get("id"))
        if not provider_job_id:
            return raw_job
        url = f"{canonical_greenhouse_jobs_api_url(request.ats_board_token)}/{provider_job_id}"
        detail_request = greenhouse_detail_request(url)
        if self.max_detail_requests is not None and self.detail_requests_attempted >= self.max_detail_requests:
            self.detail_requests_skipped += 1
            return merge_greenhouse_job_payloads(
                list_job=raw_job,
                retrieve_job=None,
                retrieve_request=detail_request,
                retrieve_skipped={
                    "reason": "max_detail_requests_reached",
                    "maxDetailRequests": self.max_detail_requests,
                },
            )
        self.detail_requests_attempted += 1
        try:
            detail = fetch_json(url, params=self.detail_request_params)
        except urllib.error.HTTPError as error:
            self.detail_requests_failed += 1
            return merge_greenhouse_job_payloads(
                list_job=raw_job,
                retrieve_job=None,
                retrieve_request=detail_request,
                retrieve_error=safe_greenhouse_detail_error(error),
            )
        except Exception as error:
            self.detail_requests_failed += 1
            return merge_greenhouse_job_payloads(
                list_job=raw_job,
                retrieve_job=None,
                retrieve_request=detail_request,
                retrieve_error=safe_greenhouse_detail_error(error),
            )
        if not isinstance(detail, dict):
            self.detail_requests_failed += 1
            return merge_greenhouse_job_payloads(
                list_job=raw_job,
                retrieve_job=None,
                retrieve_request=detail_request,
                retrieve_error={
                    "type": type(detail).__name__,
                    "message": "Greenhouse retrieve-job response was not a JSON object.",
                },
            )
        self.detail_requests_succeeded += 1
        return merge_greenhouse_job_payloads(list_job=raw_job, retrieve_job=detail, retrieve_request=detail_request)

    def reset_detail_counts(self) -> None:
        self.detail_requests_attempted = 0
        self.detail_requests_succeeded = 0
        self.detail_requests_failed = 0
        self.detail_requests_skipped = 0

    def normalize_provider_record(
        self,
        raw: object,
        request: JobSyncRequest,
        *,
        session: Session,
    ) -> tuple[NormalizedJobListing, JobListingSourceRecord] | None:
        if not isinstance(raw, dict) or not request.ats_board_token:
            return None
        title = clean_text_value(raw.get("title"))
        source_url = clean_text_value(raw.get("absolute_url"))
        provider_job_id = clean_text_value(raw.get("id"))
        company_name = request.company_name or request.ats_board_token.replace("-", " ").replace("_", " ").title()
        if not title or not company_name or not source_url or not provider_job_id:
            return None
        full_description = html_to_text(str(raw.get("content") or "")) or None
        location_raw = clean_text_value(nested_get(raw, "location", "name"))
        location_payload = raw.get("location") if isinstance(raw.get("location"), dict) else None
        location_target = resolve_or_create_job_location_from_provider_payload(
            session,
            provider_name=self.provider_name,
            raw_display_location=location_raw,
            provider_location_payload=location_payload,
            provider_country=request.provider_country,
        )
        source_updated_at = parse_datetime_value(raw.get("updated_at"))
        listing = NormalizedJobListing(
            title=title,
            company_name=company_name,
            job_location_target_id=location_target.id,
            company_id=request.company_id,
            canonical_url=source_url,
            apply_url=source_url,
            source_url=source_url,
            location_raw=location_raw,
            location_display=location_target.display_name or location_raw,
            location_city=location_target.city,
            location_region=location_target.region,
            location_country=location_target.country_code,
            location_metro=location_target.city,
            location_confidence=location_target.confidence,
            remote_work_mode=infer_remote_mode(f"{title} {full_description or ''}"),
            full_description=full_description,
            description_excerpt=full_description[:600] if full_description else None,
            source_updated_at=source_updated_at,
            source_status="active",
        )
        source = JobListingSourceRecord(
            source_provider=self.provider_name,
            provider_type=self.provider_type,
            provider_job_id=provider_job_id,
            source_result_id=f"{request.ats_board_token}:{provider_job_id}" if provider_job_id else None,
            ats_provider="greenhouse",
            ats_board_token=request.ats_board_token,
            source_url=source_url,
            apply_url=source_url,
            canonical_url=source_url,
            source_query=request.query_text,
            source_location=request.display_location,
            source_country=request.provider_country,
            raw_location=location_raw,
            raw_metadata_json=copy_greenhouse_raw_metadata(raw),
            source_updated_at=source_updated_at,
            source_status="active",
        )
        return listing, source


def merge_greenhouse_job_payloads(
    *,
    list_job: dict[str, object],
    retrieve_job: dict[str, object] | None,
    retrieve_request: dict[str, object],
    retrieve_error: dict[str, object] | None = None,
    retrieve_skipped: dict[str, object] | None = None,
) -> dict[str, object]:
    merged = {**list_job, **(retrieve_job or {})}
    merged["job_board_list_payload"] = list_job
    merged["job_board_retrieve_payload"] = retrieve_job
    merged["job_board_retrieve_request"] = retrieve_request
    if retrieve_error is not None:
        merged["job_board_retrieve_error"] = retrieve_error
    if retrieve_skipped is not None:
        merged["job_board_retrieve_skipped"] = retrieve_skipped
    return merged


def copy_greenhouse_raw_metadata(raw: dict[str, object]) -> dict[str, object]:
    return dict(raw)


def greenhouse_detail_request(url: str) -> dict[str, object]:
    return {"url": url, "params": dict(GreenhouseJobSyncProvider.detail_request_params)}


def safe_greenhouse_detail_error(error: Exception) -> dict[str, object]:
    detail: dict[str, object] = {
        "type": type(error).__name__,
        "message": "Greenhouse retrieve-job request failed.",
    }
    status = getattr(error, "code", None)
    if isinstance(status, int):
        detail["status"] = status
    return detail
