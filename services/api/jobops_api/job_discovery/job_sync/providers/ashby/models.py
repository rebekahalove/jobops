from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AshbyBoardSyncTarget:
    board_url: str
    org_slug: str | None = None
    company_id: str | None = None
    company_name: str | None = None
    source: str = "configured"


@dataclass(frozen=True)
class AshbyListJobsResult:
    jobs: tuple[object, ...]
    provider_job_ids: tuple[str, ...]
    valid: bool
    error: str | None = None
