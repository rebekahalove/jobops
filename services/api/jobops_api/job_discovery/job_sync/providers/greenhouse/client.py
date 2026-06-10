from __future__ import annotations

import urllib.error

from ....provider_utils import clean_text_value, fetch_json
from ....providers.greenhouse import canonical_greenhouse_jobs_api_url, normalize_greenhouse_board_token
from .diagnostics import GREENHOUSE_DETAIL_REQUEST_PARAMS, GreenhouseDetailRequestStats, greenhouse_detail_request, safe_greenhouse_detail_error
from .models import GreenhouseDetailFetchResult, GreenhouseListJobsResult


class GreenhouseJobBoardClient:
    def __init__(self, *, max_detail_requests: int | None = None) -> None:
        self.max_detail_requests = max_detail_requests
        self.detail_stats = GreenhouseDetailRequestStats()

    def reset(self) -> None:
        self.detail_stats = GreenhouseDetailRequestStats()

    def diagnostics_json(self) -> dict[str, object]:
        return self.detail_stats.to_json()

    def list_board_jobs(self, board_token: str) -> GreenhouseListJobsResult:
        token = normalize_greenhouse_board_token(board_token)
        payload = fetch_json(canonical_greenhouse_jobs_api_url(token), params={"content": "true"})
        if not isinstance(payload, dict):
            return GreenhouseListJobsResult(
                jobs=(),
                provider_job_ids=(),
                valid=False,
                error="Greenhouse list-jobs response was not a JSON object.",
            )
        raw_jobs = payload.get("jobs")
        if not isinstance(raw_jobs, list):
            return GreenhouseListJobsResult(
                jobs=(),
                provider_job_ids=(),
                valid=False,
                error="Greenhouse list-jobs response did not include a jobs array.",
            )
        provider_job_ids = tuple(
            provider_job_id
            for raw_job in raw_jobs
            if isinstance(raw_job, dict)
            for provider_job_id in [clean_text_value(raw_job.get("id"))]
            if provider_job_id
        )
        return GreenhouseListJobsResult(
            jobs=tuple(raw_jobs),
            provider_job_ids=provider_job_ids,
            valid=True,
        )

    def retrieve_job_detail(self, *, board_token: str, raw_job: object) -> GreenhouseDetailFetchResult | object:
        if not isinstance(raw_job, dict):
            return raw_job
        provider_job_id = clean_text_value(raw_job.get("id"))
        if not provider_job_id:
            return GreenhouseDetailFetchResult(list_job=raw_job)
        url = f"{canonical_greenhouse_jobs_api_url(board_token)}/{provider_job_id}"
        detail_request = greenhouse_detail_request(url)
        if self.max_detail_requests is not None and self.detail_stats.attempted >= self.max_detail_requests:
            self.detail_stats.skipped_by_guardrail += 1
            return GreenhouseDetailFetchResult(
                list_job=raw_job,
                retrieve_request=detail_request,
                retrieve_skipped={
                    "reason": "max_detail_requests_reached",
                    "maxDetailRequests": self.max_detail_requests,
                },
            )
        self.detail_stats.attempted += 1
        try:
            detail = fetch_json(url, params=GREENHOUSE_DETAIL_REQUEST_PARAMS)
        except urllib.error.HTTPError as error:
            self.detail_stats.failed += 1
            return GreenhouseDetailFetchResult(
                list_job=raw_job,
                retrieve_request=detail_request,
                retrieve_error=safe_greenhouse_detail_error(error),
            )
        except Exception as error:
            self.detail_stats.failed += 1
            return GreenhouseDetailFetchResult(
                list_job=raw_job,
                retrieve_request=detail_request,
                retrieve_error=safe_greenhouse_detail_error(error),
            )
        if not isinstance(detail, dict):
            self.detail_stats.failed += 1
            return GreenhouseDetailFetchResult(
                list_job=raw_job,
                retrieve_request=detail_request,
                retrieve_error={
                    "type": type(detail).__name__,
                    "message": "Greenhouse retrieve-job response was not a JSON object.",
                },
            )
        self.detail_stats.succeeded += 1
        return GreenhouseDetailFetchResult(
            list_job=raw_job,
            retrieve_request=detail_request,
            retrieve_job=detail,
        )
