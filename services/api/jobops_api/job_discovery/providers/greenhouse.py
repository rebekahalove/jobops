from __future__ import annotations

from dataclasses import dataclass, replace
import re
import urllib.error
from typing import Any
from urllib.parse import urlparse

from ...settings import Settings
from .base import JobSearchRequest, LiveJobSourceResult, ProviderDiagnostic, ProviderSearchOutcome, ProviderType
from ..provider_utils import (
    clean_text_value,
    compact_unique_strings,
    fetch_json,
    html_to_text,
    infer_remote_mode,
    nested_get,
    parse_datetime_value,
    safe_provider_raw_metadata,
)


GREENHOUSE_BOARD_HOSTS = {"boards.greenhouse.io", "job-boards.greenhouse.io"}
GREENHOUSE_API_HOST = "boards-api.greenhouse.io"


@dataclass(frozen=True)
class GreenhouseUrlParts:
    provider: str
    board_token: str
    job_id: str | None
    jobs_api_url: str


@dataclass(frozen=True)
class GreenhouseBoardTarget:
    board_token: str
    company_name: str | None = None
    reason: str = "configured_board_token"


class GreenhouseJobDiscoveryProvider:
    provider_name = "greenhouse"
    provider_type: ProviderType = "ats_board"

    def is_configured(self, settings: Settings) -> bool:
        return bool(resolve_greenhouse_board_tokens(settings))

    def search(self, request: JobSearchRequest, settings: Settings) -> ProviderSearchOutcome:
        results: list[LiveJobSourceResult] = []
        diagnostics: list[ProviderDiagnostic] = []
        errors: list[str] = []
        for target in resolve_greenhouse_board_targets(settings, request=request):
            token = target.board_token
            url = canonical_greenhouse_jobs_api_url(token)
            try:
                payload = fetch_json(url, params={"content": "true"})
            except urllib.error.HTTPError as error:
                message = f"Greenhouse board {token} returned HTTP {error.code}."
                diagnostics.append(
                    ProviderDiagnostic(
                        provider_name=self.provider_name,
                        provider_type=self.provider_type,
                        configured=True,
                        attempted=True,
                        result_count=0,
                        error=message,
                        board_token=token,
                    )
                )
                errors.append(message)
                continue
            except Exception as error:
                message = f"Greenhouse board {token} request failed: {type(error).__name__}"
                diagnostics.append(
                    ProviderDiagnostic(
                        provider_name=self.provider_name,
                        provider_type=self.provider_type,
                        configured=True,
                        attempted=True,
                        result_count=0,
                        error=message,
                        board_token=token,
                    )
                )
                errors.append(message)
                continue
            raw_jobs = payload.get("jobs") if isinstance(payload, dict) else []
            if not isinstance(raw_jobs, list):
                raw_jobs = []
            board_results = [
                result
                for raw in raw_jobs
                if (result := normalize_greenhouse_result(raw, board_token=token, request=request, company_name=target.company_name))
            ]
            query = request.search_queries[0] if request.search_queries else None
            if query:
                board_results = [result for result in board_results if source_result_matches_query(result, query)]
            results.extend(board_results)
            diagnostics.append(
                ProviderDiagnostic(
                    provider_name=self.provider_name,
                    provider_type=self.provider_type,
                    configured=True,
                    attempted=True,
                    result_count=len(board_results),
                    raw_result_count=len(raw_jobs),
                    normalized_result_count=len(board_results),
                    query=query,
                    board_token=token,
                    company_name=target.company_name,
                    search_mode=request.search_plan.search_mode if request.search_plan is not None else "board_fetch_local_filter",
                    reason=target.reason,
                )
            )
        return ProviderSearchOutcome(results=results, diagnostics=diagnostics, errors=errors)


def resolve_greenhouse_board_tokens(settings: Settings, request: JobSearchRequest | None = None) -> tuple[str, ...]:
    return tuple(target.board_token for target in resolve_greenhouse_board_targets(settings, request=request))


def resolve_greenhouse_board_targets(settings: Settings, request: JobSearchRequest | None = None) -> tuple[GreenhouseBoardTarget, ...]:
    targets: list[GreenhouseBoardTarget] = [
        GreenhouseBoardTarget(board_token=token, reason="configured_board_token")
        for token in settings.greenhouse_board_tokens
    ]
    requested_companies = {name.casefold() for name in (request.company_names or [])} if request else set()
    search_mode = request.search_plan.search_mode if request and request.search_plan is not None else None
    include_saved_company_boards = search_mode in {"company_specific", "followed_companies"} or bool(requested_companies)

    if settings.greenhouse_company_boards:
        for company_name, token in settings.greenhouse_company_boards.items():
            if include_saved_company_boards and (not requested_companies or company_name.casefold() in requested_companies):
                targets.append(
                    GreenhouseBoardTarget(
                        board_token=token,
                        company_name=company_name,
                        reason="configured_company_board_token",
                    )
                )

    if request and include_saved_company_boards:
        for company in request.current_saved_companies:
            token = greenhouse_board_token_from_company(company)
            if not token:
                continue
            company_name = clean_text_value(company.get("name"))
            if requested_companies and (company_name or "").casefold() not in requested_companies:
                continue
            targets.append(
                GreenhouseBoardTarget(
                    board_token=token,
                    company_name=company_name,
                    reason="saved_company_board_token",
                )
            )

    deduped: list[GreenhouseBoardTarget] = []
    seen: set[str] = set()
    for target in targets:
        token = normalize_greenhouse_board_token(target.board_token)
        key = token.casefold()
        if not token or key in seen:
            continue
        seen.add(key)
        deduped.append(GreenhouseBoardTarget(board_token=token, company_name=target.company_name, reason=target.reason))
        if len(deduped) >= 100:
            break
    return tuple(deduped)


def normalize_greenhouse_result(
    raw: object,
    *,
    board_token: str,
    request: JobSearchRequest,
    company_name: str | None = None,
) -> LiveJobSourceResult | None:
    if not isinstance(raw, dict):
        return None
    title = clean_text_value(raw.get("title"))
    job_url = clean_text_value(raw.get("absolute_url"))
    job_id = raw.get("id")
    resolved_company_name = company_name or company_name_for_greenhouse_board(board_token, request.current_saved_companies)
    if not title or not resolved_company_name or not job_url:
        return None
    full_description = html_to_text(str(raw.get("content") or "")) or None
    content = full_description[:600] if full_description else None
    updated_at = parse_datetime_value(raw.get("updated_at"))
    return LiveJobSourceResult(
        title=title,
        company_name=resolved_company_name,
        job_url=job_url,
        apply_url=job_url,
        source_provider="greenhouse",
        provider_type="ats_board",
        source_result_id=f"{board_token}:{job_id}" if job_id is not None else board_token,
        source_query=request.search_queries[0] if request.search_queries else None,
        source_url=job_url,
        provenance="provider_result",
        location=clean_text_value(nested_get(raw, "location", "name")),
        remote_work_mode=infer_remote_mode(f"{title} {content or ''}"),
        full_description=full_description,
        description_excerpt=content,
        posting_date=None,
        source_updated_at=updated_at,
        ats_provider="greenhouse",
        ats_board_token=board_token,
        company_job_listings_url=canonical_greenhouse_jobs_api_url(board_token),
        source_urls=(canonical_greenhouse_jobs_api_url(board_token),),
        raw_metadata=safe_provider_raw_metadata(raw),
        url_verification_status="provider_unverified",
        url_verification_summary="Greenhouse public job board result.",
    )


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


def fetch_greenhouse_job_from_url(url: str, request: JobSearchRequest) -> LiveJobSourceResult | None:
    parts = parse_greenhouse_url(url)
    if parts is None or not parts.job_id:
        return None
    payload = fetch_json(parts.jobs_api_url, params={"content": "true"})
    raw_jobs = payload.get("jobs") if isinstance(payload, dict) else []
    if not isinstance(raw_jobs, list):
        raw_jobs = []
    raw_job = next((raw for raw in raw_jobs if greenhouse_raw_job_matches_id(raw, parts.job_id)), None)
    if raw_job is None:
        return None
    company_name = company_name_for_greenhouse_board(parts.board_token, request.current_saved_companies)
    result = normalize_greenhouse_result(raw_job, board_token=parts.board_token, request=request, company_name=company_name)
    if result is None:
        return None
    return replace(
        result,
        provenance="provider_result",
        source_url=url,
        fit_summary="Saved from a Greenhouse public job posting URL.",
        url_verification_summary="Greenhouse public job board URL ingestion.",
    )


def greenhouse_raw_job_matches_id(raw: object, job_id: str) -> bool:
    if not isinstance(raw, dict):
        return False
    if str(raw.get("id") or "").strip() == job_id:
        return True
    absolute_url = clean_text_value(raw.get("absolute_url")) or ""
    return f"/jobs/{job_id}" in absolute_url


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


def company_name_for_greenhouse_board(board_token: str, current_saved_companies: list[dict[str, Any]]) -> str:
    for company in current_saved_companies:
        direct_token = greenhouse_board_token_from_company(company)
        if direct_token and direct_token.casefold() == board_token.casefold():
            name = clean_text_value(company.get("name"))
            if name:
                return name
        values = [
            company.get("job_listings_url"),
            company.get("jobListingsUrl"),
            company.get("careers_url"),
            company.get("careersUrl"),
            *(company.get("source_urls") or company.get("sourceUrls") or []),
        ]
        if any(isinstance(value, str) and board_token.casefold() in value.casefold() for value in values):
            name = clean_text_value(company.get("name"))
            if name:
                return name
    return board_token.replace("-", " ").replace("_", " ").title()


def source_result_matches_query(result: LiveJobSourceResult, query: str) -> bool:
    terms = meaningful_query_terms(query)
    if not terms:
        return True
    haystack = " ".join(
        part
        for part in [
            result.title,
            result.company_name,
            result.location or "",
            result.description_excerpt or "",
        ]
        if part
    ).casefold()
    return all(term in haystack for term in terms[:3])


def meaningful_query_terms(query: str) -> list[str]:
    stop_words = {
        "job",
        "jobs",
        "opening",
        "openings",
        "opportunity",
        "opportunities",
        "position",
        "positions",
        "role",
        "roles",
        "senior",
        "staff",
        "lead",
        "remote",
        "hybrid",
        "onsite",
    }
    terms = []
    for raw in re.findall(r"[a-z0-9]+", query.casefold()):
        if len(raw) < 3 or raw in stop_words:
            continue
        terms.append(raw)
    return compact_unique_strings(terms, limit=5)
