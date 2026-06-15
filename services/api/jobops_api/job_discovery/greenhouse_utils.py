from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .provider_utils import clean_text_value


GREENHOUSE_BOARD_HOSTS = {"boards.greenhouse.io", "job-boards.greenhouse.io"}
GREENHOUSE_API_HOST = "boards-api.greenhouse.io"


@dataclass(frozen=True)
class GreenhouseUrlParts:
    provider: str
    board_token: str
    job_id: str | None
    jobs_api_url: str


def parse_greenhouse_url(value: str | None) -> GreenhouseUrlParts | None:
    if not value:
        return None
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"}:
        return None
    hostname = (parsed.hostname or "").casefold().removeprefix("www.")
    path_parts = [part for part in parsed.path.split("/") if part]
    board_token: str | None = None
    job_id: str | None = None

    if hostname in GREENHOUSE_BOARD_HOSTS:
        if not path_parts:
            return None
        board_token = path_parts[0]
        if len(path_parts) >= 3 and path_parts[1] == "jobs":
            job_id = path_parts[2]
    elif hostname == GREENHOUSE_API_HOST:
        if len(path_parts) >= 4 and path_parts[0] == "v1" and path_parts[1] == "boards" and path_parts[3] == "jobs":
            board_token = path_parts[2]
            if len(path_parts) >= 5:
                job_id = path_parts[4]
    else:
        return None

    token = normalize_greenhouse_board_token(board_token)
    if not token:
        return None
    return GreenhouseUrlParts(
        provider="greenhouse",
        board_token=token,
        job_id=job_id.strip() if isinstance(job_id, str) and job_id.strip() else None,
        jobs_api_url=canonical_greenhouse_jobs_api_url(token),
    )


def greenhouse_board_token_from_company(company: dict[str, Any]) -> str | None:
    for key in ("ats_board_token", "atsBoardToken", "greenhouse_board_token", "greenhouseBoardToken"):
        token = normalize_greenhouse_board_token(company.get(key))
        if token:
            return token
    for key in ("job_listings_url", "jobListingsUrl", "careers_url", "careersUrl"):
        parsed = parse_greenhouse_url(clean_text_value(company.get(key)))
        if parsed is not None:
            return parsed.board_token
    for value in company.get("source_urls") or company.get("sourceUrls") or []:
        parsed = parse_greenhouse_url(clean_text_value(value))
        if parsed is not None:
            return parsed.board_token
    return None


def canonical_greenhouse_jobs_api_url(board_token: str) -> str:
    return f"https://boards-api.greenhouse.io/v1/boards/{normalize_greenhouse_board_token(board_token)}/jobs"


def normalize_greenhouse_board_token(value: object) -> str:
    token = clean_text_value(value)
    return token.strip("/") if token else ""
