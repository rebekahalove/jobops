from __future__ import annotations

import re
import urllib.error
from typing import Any

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


class GreenhouseJobDiscoveryProvider:
    provider_name = "greenhouse"
    provider_type: ProviderType = "ats_board"

    def is_configured(self, settings: Settings) -> bool:
        return bool(resolve_greenhouse_board_tokens(settings))

    def search(self, request: JobSearchRequest, settings: Settings) -> ProviderSearchOutcome:
        results: list[LiveJobSourceResult] = []
        diagnostics: list[ProviderDiagnostic] = []
        errors: list[str] = []
        for token in resolve_greenhouse_board_tokens(settings):
            url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
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
                if (result := normalize_greenhouse_result(raw, board_token=token, request=request))
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
                    query=query,
                    board_token=token,
                    search_mode="board_fetch_local_filter",
                )
            )
        return ProviderSearchOutcome(results=results, diagnostics=diagnostics, errors=errors)


def resolve_greenhouse_board_tokens(settings: Settings) -> tuple[str, ...]:
    tokens = list(settings.greenhouse_board_tokens)
    if settings.greenhouse_company_boards:
        tokens.extend(settings.greenhouse_company_boards.values())
    return tuple(compact_unique_strings(tokens, limit=100))


def normalize_greenhouse_result(raw: object, *, board_token: str, request: JobSearchRequest) -> LiveJobSourceResult | None:
    if not isinstance(raw, dict):
        return None
    title = clean_text_value(raw.get("title"))
    job_url = clean_text_value(raw.get("absolute_url"))
    job_id = raw.get("id")
    company_name = company_name_for_greenhouse_board(board_token, request.current_saved_companies)
    if not title or not company_name or not job_url:
        return None
    full_description = html_to_text(str(raw.get("content") or "")) or None
    content = full_description[:600] if full_description else None
    updated_at = parse_datetime_value(raw.get("updated_at"))
    return LiveJobSourceResult(
        title=title,
        company_name=company_name,
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
        raw_metadata=safe_provider_raw_metadata(raw),
        url_verification_status="provider_unverified",
        url_verification_summary="Greenhouse public job board result.",
    )


def company_name_for_greenhouse_board(board_token: str, current_saved_companies: list[dict[str, Any]]) -> str:
    for company in current_saved_companies:
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
