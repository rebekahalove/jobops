from __future__ import annotations

from collections.abc import Iterable

from ...provider_utils import (
    clean_text_value,
    fetch_json,
    format_salary_text,
    html_to_text,
    infer_adzuna_currency_code,
    infer_remote_mode,
    nested_get,
    parse_datetime_value,
    parse_whole_currency_amount,
)
from ..base import BaseJobSyncProvider
from ..models import (
    BroadJobSyncSignature,
    JobListingSourceRecord,
    JobSyncLocation,
    JobSyncPlan,
    JobSyncRequest,
    NormalizedJobListing,
    normalize_job_sync_location,
    normalize_provider_country,
)
from ..service import build_adzuna_sync_key, normalize_sync_key_text


class AdzunaJobSyncProvider(BaseJobSyncProvider):
    provider_name = "adzuna"
    provider_type = "broad_search"

    def __init__(self, *, app_id: str | None = None, app_key: str | None = None, results_per_page: int = 50) -> None:
        self.app_id = app_id
        self.app_key = app_key
        self.results_per_page = max(1, min(results_per_page, 50))

    def build_sync_plan(
        self,
        *,
        provider_country: str,
        locations: Iterable[str | None],
        queries: Iterable[str],
        results_per_page: int | None = None,
    ) -> JobSyncPlan:
        country = normalize_provider_country(provider_country) or "us"
        requests: list[JobSyncRequest] = []
        for query in queries:
            query_text = " ".join((query or "").split()).strip()
            if not query_text:
                continue
            for raw_location in locations:
                location = normalize_job_sync_location(raw_location, default_provider_country=country)
                signature = build_adzuna_broad_sync_signature(country, location, query_text)
                request = build_adzuna_sync_request(
                    signature,
                    location=location,
                    query_text=query_text,
                    results_per_page=results_per_page or self.results_per_page,
                    page=1,
                )
                requests.append(request)
        return JobSyncPlan(requests=tuple(requests))

    def fetch_provider_records(self, request: JobSyncRequest) -> Iterable[object]:
        if not self.app_id or not self.app_key:
            raise ValueError("Adzuna Job Sync requires app_id and app_key.")
        page = int(request.criteria_json.get("page") or 1)
        api_path = str(request.criteria_json.get("apiPath") or f"/v1/api/jobs/{request.provider_country}/search/{page}")
        url = f"https://api.adzuna.com{api_path}"
        params: dict[str, object] = {
            "app_id": self.app_id,
            "app_key": self.app_key,
            "what": request.query_text or "",
            "results_per_page": request.criteria_json.get("resultsPerPage") or self.results_per_page,
            "content-type": "application/json",
        }
        if request.provider_where:
            params["where"] = request.provider_where
        what_exclude = request.criteria_json.get("whatExclude")
        if what_exclude:
            params["what_exclude"] = what_exclude
        payload = fetch_json(url, params=params)
        raw_results = payload.get("results") if isinstance(payload, dict) else []
        return raw_results if isinstance(raw_results, list) else []

    def normalize_provider_record(
        self,
        raw: object,
        request: JobSyncRequest,
    ) -> tuple[NormalizedJobListing, JobListingSourceRecord] | None:
        if not isinstance(raw, dict):
            return None
        title = clean_text_value(raw.get("title"))
        company_name = clean_text_value(nested_get(raw, "company", "display_name"))
        source_url = clean_text_value(raw.get("redirect_url"))
        if not title or not company_name or not source_url:
            return None
        provider_country = normalize_provider_country(request.provider_country) or "us"
        provider_job_id = clean_text_value(raw["id"]) if "id" in raw else None
        if not provider_job_id:
            return None
        salary_currency = infer_adzuna_currency_code(provider_country)
        salary_min = parse_whole_currency_amount(raw.get("salary_min"))
        salary_max = parse_whole_currency_amount(raw.get("salary_max"))
        created = parse_datetime_value(raw.get("created"))
        full_description = html_to_text(str(raw.get("description") or "")) or None
        location_raw = clean_text_value(nested_get(raw, "location", "display_name"))
        location = normalize_job_sync_location(location_raw or request.display_location, default_provider_country=provider_country)
        listing = NormalizedJobListing(
            title=title,
            company_name=company_name,
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
            remote_work_mode=infer_remote_mode(" ".join(str(raw.get(key) or "") for key in ("title", "description"))),
            employment_type=clean_text_value(raw.get("contract_time") or raw.get("contract_type")),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=salary_currency,
            salary_text=format_salary_text(raw.get("salary_min"), raw.get("salary_max"), currency_code=salary_currency),
            full_description=full_description,
            description_excerpt=full_description[:600] if full_description else None,
            posting_date=created.date() if created else None,
            source_updated_at=created,
            source_status="active",
        )
        source = JobListingSourceRecord(
            source_provider=self.provider_name,
            provider_type=self.provider_type,
            provider_job_id=provider_job_id,
            source_result_id=provider_job_id,
            source_url=source_url,
            apply_url=source_url,
            canonical_url=source_url,
            source_query=request.query_text,
            source_location=request.display_location,
            source_country=provider_country,
            raw_location=location_raw,
            raw_metadata_json=copy_adzuna_raw_metadata(raw),
            source_updated_at=created,
            source_status="active",
        )
        return listing, source


def copy_adzuna_raw_metadata(raw: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in raw.items()
        if key.casefold() not in {"app_id", "app_key", "authorization", "cookie", "cookies", "token"}
    }


def build_adzuna_broad_sync_signature(
    provider_country: str,
    location: JobSyncLocation,
    query_text: str,
) -> BroadJobSyncSignature:
    country = normalize_provider_country(provider_country) or location.provider_country
    location_key = normalize_sync_key_text(location.provider_where or location.display_location or location.provider_country)
    sync_key = build_adzuna_sync_key(country, location_key, query_text)
    return BroadJobSyncSignature(
        provider_country=country,
        location_key=location_key,
        query_text=query_text,
        sync_key=sync_key,
    )


def build_adzuna_sync_request(
    signature: BroadJobSyncSignature,
    *,
    location: JobSyncLocation,
    query_text: str,
    results_per_page: int,
    page: int,
    what_exclude: str | None = None,
) -> JobSyncRequest:
    api_path = f"/v1/api/jobs/{signature.provider_country}/search/{max(1, page)}"
    return JobSyncRequest(
        sync_key=signature.sync_key,
        provider_name=AdzunaJobSyncProvider.provider_name,
        provider_type=AdzunaJobSyncProvider.provider_type,
        sync_kind="broad_search",
        provider_country=signature.provider_country,
        target_country=location.target_country,
        target_location_kind=location.target_location_kind,
        display_location=location.display_location,
        provider_where=location.provider_where,
        query_text=query_text,
        query_kind="role_query",
        criteria_json={
            "providerCountry": signature.provider_country,
            "apiPath": api_path,
            "page": max(1, page),
            "what": query_text,
            "where": location.provider_where,
            "whatExclude": what_exclude,
            "resultsPerPage": max(1, min(results_per_page, 50)),
            "contentType": "application/json",
            "syncKey": signature.sync_key,
        },
    )
