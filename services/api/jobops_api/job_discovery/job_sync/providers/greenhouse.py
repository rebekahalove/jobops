from __future__ import annotations

import urllib.error
from collections.abc import Iterable

from ...provider_utils import clean_text_value, fetch_json, html_to_text, infer_remote_mode, nested_get, parse_datetime_value
from ...providers.greenhouse import canonical_greenhouse_jobs_api_url, normalize_greenhouse_board_token
from ..base import BaseJobSyncProvider
from ..models import JobListingSourceRecord, JobSyncPlan, JobSyncRequest, NormalizedJobListing, normalize_job_sync_location
from ..service import build_greenhouse_sync_key


class GreenhouseJobSyncProvider(BaseJobSyncProvider):
    provider_name = "greenhouse"
    provider_type = "ats_board"

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
                        "syncKey": build_greenhouse_sync_key(board_token),
                    },
                )
            )
        return JobSyncPlan(requests=tuple(requests))

    def fetch_provider_records(self, request: JobSyncRequest) -> Iterable[object]:
        if not request.ats_board_token:
            raise ValueError("Greenhouse Job Sync requests require ats_board_token.")
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
        detail = fetch_json(url, params={"questions": "true", "pay_transparency": "true"})
        if not isinstance(detail, dict):
            return raw_job
        return merge_greenhouse_job_payloads(list_job=raw_job, retrieve_job=detail)

    def normalize_provider_record(
        self,
        raw: object,
        request: JobSyncRequest,
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
        location = normalize_job_sync_location(location_raw, default_provider_country="us")
        source_updated_at = parse_datetime_value(raw.get("updated_at"))
        listing = NormalizedJobListing(
            title=title,
            company_name=company_name,
            company_id=request.company_id,
            canonical_url=source_url,
            apply_url=source_url,
            source_url=source_url,
            location_raw=location_raw,
            location_display=location.display_location or location_raw,
            location_city=location.location_city,
            location_region=location.location_region,
            location_country=location.location_country,
            location_metro=location.location_metro,
            location_confidence=location.location_confidence,
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


def merge_greenhouse_job_payloads(*, list_job: dict[str, object], retrieve_job: dict[str, object]) -> dict[str, object]:
    merged = {**list_job, **retrieve_job}
    merged["job_board_list_payload"] = list_job
    merged["job_board_retrieve_payload"] = retrieve_job
    return merged


def copy_greenhouse_raw_metadata(raw: dict[str, object]) -> dict[str, object]:
    return dict(raw)
