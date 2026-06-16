from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse


@dataclass(frozen=True)
class AshbyJobBoardUrl:
    org_slug: str
    canonical_board_url: str
    job_id: str | None = None


def parse_ashby_job_board_url(value: object) -> AshbyJobBoardUrl | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    if parsed.scheme not in {"http", "https"} or parsed.hostname != "jobs.ashbyhq.com":
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        return None
    org_slug = normalize_ashby_org_slug(parts[0])
    if not org_slug:
        return None
    job_id = None
    if len(parts) >= 2 and parts[1] != "application":
        job_id = parts[1]
    return AshbyJobBoardUrl(
        org_slug=org_slug,
        canonical_board_url=canonical_ashby_board_url(org_slug),
        job_id=job_id,
    )


def normalize_ashby_org_slug(value: object) -> str:
    cleaned = str(value or "").strip().strip("/")
    return cleaned if cleaned and "/" not in cleaned else ""


def canonical_ashby_board_url(org_slug: str) -> str:
    return urlunparse(("https", "jobs.ashbyhq.com", f"/{normalize_ashby_org_slug(org_slug)}", "", "", ""))


def ashby_posting_api_url(org_slug: str) -> str:
    return f"https://api.ashbyhq.com/posting-api/job-board/{normalize_ashby_org_slug(org_slug)}"
