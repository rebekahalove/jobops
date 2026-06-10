from __future__ import annotations

from dataclasses import dataclass


GREENHOUSE_MISSING_CLOSE_REASON = "missing_from_latest_greenhouse_board_sync"


@dataclass(frozen=True)
class GreenhouseBoardSyncTarget:
    board_token: str
    company_id: str | None = None
    company_name: str | None = None
    source: str = "configured"


@dataclass(frozen=True)
class GreenhouseListJobsResult:
    jobs: tuple[object, ...]
    provider_job_ids: tuple[str, ...]
    valid: bool
    error: str | None = None


@dataclass(frozen=True)
class GreenhouseDetailFetchResult:
    list_job: dict[str, object]
    retrieve_request: dict[str, object] | None = None
    retrieve_job: dict[str, object] | None = None
    retrieve_error: dict[str, object] | None = None
    retrieve_skipped: dict[str, object] | None = None
