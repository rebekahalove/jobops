from __future__ import annotations

import urllib.error
from dataclasses import replace
from typing import Any

from ...settings import Settings
from .base import JobProviderRuntimeError, JobSearchRequest, LiveJobSourceResult, ProviderDiagnostic, ProviderSearchOutcome, ProviderType
from ..provider_utils import (
    build_adzuna_exclusions,
    clean_text_value,
    dedupe_provider_results,
    fetch_json,
    format_salary_text,
    html_to_text,
    infer_adzuna_currency_code,
    infer_location_query,
    infer_remote_mode,
    nested_get,
    parse_datetime_value,
    parse_whole_currency_amount,
    safe_provider_raw_metadata,
)


class AdzunaJobDiscoveryProvider:
    provider_name = "adzuna"
    provider_type: ProviderType = "broad_search"

    def is_configured(self, settings: Settings) -> bool:
        return bool(settings.adzuna_app_id and settings.adzuna_app_key)

    def search(self, request: JobSearchRequest, settings: Settings) -> ProviderSearchOutcome:
        queries = request.search_queries[:3] or [request.latest_user_message]
        results_per_query = max(5, min(20, (request.results_per_provider + len(queries) - 1) // len(queries)))
        results: list[LiveJobSourceResult] = []
        diagnostics: list[ProviderDiagnostic] = []
        errors: list[str] = []
        for query in queries:
            query_request = replace(request, results_per_provider=results_per_query)
            url, params = build_adzuna_request(settings, query_request, query=query)
            try:
                payload = fetch_json(url, params=params)
            except urllib.error.HTTPError as error:
                raise JobProviderRuntimeError(f"Adzuna request failed with HTTP {error.code}.") from error
            except urllib.error.URLError as error:
                raise JobProviderRuntimeError(f"Adzuna request failed: {type(error.reason).__name__}") from error
            except Exception as error:
                raise JobProviderRuntimeError(f"Adzuna request failed: {type(error).__name__}") from error
            raw_results = payload.get("results") if isinstance(payload, dict) else []
            if not isinstance(raw_results, list):
                raw_results = []
            query_results = [
                result for raw in raw_results if (result := normalize_adzuna_result(raw, query=query, settings=settings))
            ]
            results.extend(query_results)
            diagnostics.append(
                ProviderDiagnostic(
                    provider_name=self.provider_name,
                    provider_type=self.provider_type,
                    configured=True,
                    attempted=True,
                    result_count=len(query_results),
                    raw_result_count=len(raw_results),
                    query=query,
                    search_mode="broad_keyword_search",
                )
            )
        results = dedupe_provider_results(results)[: request.results_per_provider]
        return ProviderSearchOutcome(results=results, diagnostics=diagnostics, errors=errors)


def build_adzuna_request(settings: Settings, request: JobSearchRequest, *, query: str) -> tuple[str, dict[str, object]]:
    country = settings.adzuna_country or "us"
    url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
    params: dict[str, object] = {
        "app_id": settings.adzuna_app_id,
        "app_key": settings.adzuna_app_key,
        "what": query,
        "results_per_page": request.results_per_provider,
        "content-type": "application/json",
    }
    where = infer_location_query(request.latest_user_message, request.target_context, request.private_profile_context)
    if where:
        params["where"] = where
    exclusions = build_adzuna_exclusions(request.user_constraints)
    if exclusions:
        params["what_exclude"] = exclusions
    return url, params


def normalize_adzuna_result(raw: object, *, query: str, settings: Settings) -> LiveJobSourceResult | None:
    if not isinstance(raw, dict):
        return None
    title = clean_text_value(raw.get("title"))
    company_name = clean_text_value(nested_get(raw, "company", "display_name"))
    job_url = clean_text_value(raw.get("redirect_url"))
    if not title or not company_name or not job_url:
        return None
    salary_currency = infer_adzuna_currency_code(settings.adzuna_country)
    salary_min = parse_whole_currency_amount(raw.get("salary_min"))
    salary_max = parse_whole_currency_amount(raw.get("salary_max"))
    salary_text = format_salary_text(raw.get("salary_min"), raw.get("salary_max"), currency_code=salary_currency)
    created = parse_datetime_value(raw.get("created"))
    full_description = html_to_text(str(raw.get("description") or "")) or None
    return LiveJobSourceResult(
        title=title,
        company_name=company_name,
        job_url=job_url,
        apply_url=job_url,
        source_provider="adzuna",
        provider_type="broad_search",
        source_result_id=str(raw.get("id")) if raw.get("id") is not None else None,
        source_query=query,
        source_url=job_url,
        provenance="provider_result",
        location=clean_text_value(nested_get(raw, "location", "display_name")),
        remote_work_mode=infer_remote_mode(" ".join(str(raw.get(key) or "") for key in ("title", "description"))),
        employment_type=clean_text_value(raw.get("contract_time") or raw.get("contract_type")),
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=salary_currency,
        salary_text=salary_text,
        full_description=full_description,
        description_excerpt=full_description[:600] if full_description else None,
        posting_date=created.date() if created else None,
        source_updated_at=created,
        raw_metadata=safe_provider_raw_metadata(raw),
        url_verification_status="provider_unverified",
        url_verification_summary="Adzuna provider result; URL may redirect through Adzuna.",
    )
