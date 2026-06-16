from __future__ import annotations

from ....ashby_utils import ashby_posting_api_url, normalize_ashby_org_slug
from ....provider_utils import clean_text_value, fetch_json
from .models import AshbyListJobsResult


class AshbyJobBoardClient:
    def __init__(self) -> None:
        self.latest_error: str | None = None

    def diagnostics_json(self, *, org_slug: str) -> dict[str, object]:
        api_url = ashby_posting_api_url(org_slug)
        return {
            "orgSlug": org_slug,
            "boardUrl": f"https://jobs.ashbyhq.com/{org_slug}",
            "listJobsUrl": api_url,
            "listJobsResponseValid": self.latest_error is None,
            "errorSummary": self.latest_error,
        }

    def list_board_jobs(self, org_slug: str) -> AshbyListJobsResult:
        slug = normalize_ashby_org_slug(org_slug)
        self.latest_error = None
        try:
            payload = fetch_json(ashby_posting_api_url(slug))
        except Exception as error:
            self.latest_error = str(error)
            return AshbyListJobsResult(jobs=(), provider_job_ids=(), valid=False, error=str(error))
        jobs = extract_ashby_jobs(payload)
        if jobs is None:
            self.latest_error = "Ashby list-jobs response did not include a jobs array."
            return AshbyListJobsResult(jobs=(), provider_job_ids=(), valid=False, error=self.latest_error)
        provider_job_ids = tuple(
            provider_job_id
            for raw_job in jobs
            if isinstance(raw_job, dict)
            for provider_job_id in [clean_text_value(raw_job.get("id") or raw_job.get("jobId"))]
            if provider_job_id
        )
        return AshbyListJobsResult(jobs=tuple(jobs), provider_job_ids=provider_job_ids, valid=True)


def extract_ashby_jobs(payload: object) -> list[object] | None:
    if not isinstance(payload, dict):
        return None
    for key in ("jobs", "jobPostings", "postings"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    nested = payload.get("data")
    if isinstance(nested, dict):
        for key in ("jobs", "jobPostings", "postings"):
            value = nested.get(key)
            if isinstance(value, list):
                return value
    return None
