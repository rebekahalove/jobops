from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from ....provider_utils import clean_text_value
from ...base import BaseJobSyncProvider
from ...location_country import normalize_provider_country_code
from ...location_resolver import job_sync_location_from_mapping, resolve_provider_location_mapping
from ...models import BroadJobSyncSignature, JobListingSourceRecord, JobSyncLocation, JobSyncPlan, JobSyncRequest, JobSyncResult, NormalizedJobListing
from ...service import build_adzuna_sync_key, is_sync_fresh, latest_completed_sync_at, record_job_sync_run, upsert_job_listing_from_provider_record
from .....db.models import JobSyncSignature
from .client import AdzunaJobSyncClient, bounded_results_per_page
from .diagnostics import page_request_diagnostics
from .mapper import copy_adzuna_raw_metadata, infer_adzuna_provider_country_from_location, normalize_adzuna_job_record
from .models import AdzunaSearchResponse


class AdzunaJobSyncProvider(BaseJobSyncProvider):
    provider_name = "adzuna"
    provider_type = "broad_search"

    def __init__(
        self,
        *,
        app_id: str | None = None,
        app_key: str | None = None,
        results_per_page: int = 50,
        client: AdzunaJobSyncClient | None = None,
    ) -> None:
        self.client = client or AdzunaJobSyncClient(app_id=app_id, app_key=app_key, results_per_page=results_per_page)
        self.latest_search_response = AdzunaSearchResponse(pages=())

    @property
    def app_id(self) -> str | None:
        return self.client.app_id

    @property
    def app_key(self) -> str | None:
        return self.client.app_key

    @property
    def results_per_page(self) -> int:
        return self.client.results_per_page

    def build_sync_plan(
        self,
        signatures: Iterable[JobSyncSignature] | None = None,
        *,
        provider_country: str | None = None,
        locations: Iterable[str | None] | None = None,
        queries: Iterable[str] | None = None,
        db_session: Session | None = None,
        results_per_page: int | None = None,
        max_pages: int | None = None,
    ) -> JobSyncPlan:
        if signatures is not None:
            return JobSyncPlan(
                requests=tuple(
                    build_adzuna_sync_request_from_signature(
                        signature,
                        results_per_page=results_per_page,
                        max_pages=max_pages,
                    )
                    for signature in signatures
                )
            )
        if db_session is None:
            raise ValueError("Adzuna explicit sync planning requires db_session.")
        country_hint = normalize_provider_country_code(provider_country)
        requests: list[JobSyncRequest] = []
        for query in queries or ():
            query_text = clean_query_text(query)
            if not query_text:
                continue
            for raw_location in locations or ():
                mapping = resolve_provider_location_mapping(
                    db_session,
                    provider_name=self.provider_name,
                    display_location=raw_location,
                    default_provider_country=country_hint,
                )
                location = job_sync_location_from_mapping(mapping.job_location_target, mapping)
                if not location.provider_country:
                    raise ValueError(
                        "Adzuna provider country could not be resolved for location "
                        f"{location.display_location or raw_location!r}."
                    )
                signature = build_adzuna_broad_sync_signature(location.provider_country, location, query_text)
                request = build_adzuna_sync_request(
                    signature,
                    location=location,
                    query_text=query_text,
                    query_kind="role_query",
                    results_per_page=results_per_page or self.results_per_page,
                    max_pages=max_pages or 1,
                    page=1,
                )
                requests.append(request)
        return JobSyncPlan(requests=tuple(requests))

    def refresh_diagnostics(self, request: JobSyncRequest) -> dict[str, object]:
        return self.latest_search_response.diagnostics_json()

    def fetch_provider_records(self, request: JobSyncRequest) -> Iterable[object]:
        self.latest_search_response = self.client.search(request)
        return self.latest_search_response.results

    def normalize_provider_record(
        self,
        raw: object,
        request: JobSyncRequest,
        *,
        session: Session,
    ) -> tuple[NormalizedJobListing, JobListingSourceRecord] | None:
        return normalize_adzuna_job_record(raw, request, session=session)

    def refresh_inventory(
        self,
        session: Session,
        request: JobSyncRequest,
        *,
        freshness_hours: int = 24,
        force: bool = False,
    ) -> JobSyncResult:
        if not force and is_sync_fresh(session, request.sync_key, freshness_hours=freshness_hours):
            latest_completed = latest_completed_sync_at(session, request.sync_key)
            sync_result = JobSyncResult(
                request=request,
                status="skipped_fresh",
                diagnostics_json={
                    "skipReason": "fresh",
                    "freshnessHours": freshness_hours,
                    "latestCompletedAt": latest_completed.isoformat() if latest_completed else None,
                },
            )
            record_job_sync_run(session, sync_result)
            return sync_result

        try:
            raw_records = list(self.fetch_provider_records(request))
        except Exception as error:
            sync_result = JobSyncResult(
                request=request,
                status="failed",
                error=str(error),
                diagnostics_json=self.refresh_diagnostics(request),
            )
            record_job_sync_run(session, sync_result)
            return sync_result

        created_count = 0
        updated_count = 0
        failed_normalization_count = 0
        normalized_count = 0

        for raw in raw_records:
            normalized = self.normalize_provider_record(raw, request, session=session)
            if normalized is None:
                failed_normalization_count += 1
                continue
            listing, source = normalized
            result = upsert_job_listing_from_provider_record(session, listing=listing, source=source)
            normalized_count += 1
            created_count += int(result.created)
            updated_count += int(result.updated)

        diagnostics = {
            **self.refresh_diagnostics(request),
            "totalNormalizedResults": normalized_count,
        }
        page_errors = diagnostics.get("pageErrors") if isinstance(diagnostics.get("pageErrors"), list) else []
        status = "completed"
        error = None
        if page_errors and raw_records:
            status = "partial"
            diagnostics["partialSync"] = True
            diagnostics["completionStatus"] = "partial_page_failure"
        elif page_errors:
            status = "failed"
            error = clean_text_value(page_errors[0].get("message")) or "Adzuna page request failed before any results were fetched."
            diagnostics["completionStatus"] = "failed_page_request"

        sync_result = JobSyncResult(
            request=request,
            status=status,
            error=error,
            raw_result_count=len(raw_records),
            normalized_count=normalized_count,
            created_count=created_count,
            updated_count=updated_count,
            failed_normalization_count=failed_normalization_count,
            diagnostics_json=diagnostics,
        )
        record_job_sync_run(session, sync_result)
        return sync_result


def clean_query_text(value: str | None) -> str:
    return " ".join((value or "").split()).strip()


def build_adzuna_broad_sync_signature(
    provider_country: str,
    location: JobSyncLocation,
    query_text: str,
) -> BroadJobSyncSignature:
    country = normalize_provider_country_code(provider_country)
    if not country:
        raise ValueError("Adzuna broad sync signatures require provider_country.")
    location_key = clean_text_value(location.normalized_key or location.provider_where or location.display_location or location.provider_country)
    sync_key = build_adzuna_sync_key(country, location_key, query_text)
    return BroadJobSyncSignature(
        provider_country=country,
        location_key=location_key or "any-location",
        query_text=query_text,
        sync_key=sync_key,
    )


def build_adzuna_sync_request_from_signature(
    signature: JobSyncSignature,
    *,
    results_per_page: int | None = None,
    max_pages: int | None = None,
) -> JobSyncRequest:
    criteria = dict(signature.criteria_json or {})
    resolved_results_per_page = bounded_results_per_page(results_per_page or signature.results_per_page or 50)
    resolved_max_pages = max(1, max_pages or signature.max_pages or 1)
    criteria.update(
        {
            "providerName": signature.provider_name,
            "providerCountry": signature.provider_country,
            "apiPath": f"/v1/api/jobs/{signature.provider_country}/search/1" if signature.provider_country else None,
            "page": 1,
            "maxPages": resolved_max_pages,
            "what": signature.query_text,
            "where": signature.provider_where,
            "resultsPerPage": resolved_results_per_page,
            "contentType": "application/json",
            "syncKey": signature.sync_key,
            "jobSyncSignatureId": signature.id,
        }
    )
    return JobSyncRequest(
        job_sync_signature_id=signature.id,
        sync_key=signature.sync_key,
        provider_name=signature.provider_name,
        provider_type=signature.provider_type,
        sync_kind=signature.sync_kind,
        provider_country=signature.provider_country,
        display_location=signature.display_location,
        provider_where=signature.provider_where,
        query_text=signature.query_text,
        query_kind=signature.query_kind,
        criteria_json=criteria,
    )


def build_adzuna_sync_request(
    signature: BroadJobSyncSignature,
    *,
    location: JobSyncLocation,
    query_text: str,
    query_kind: str,
    results_per_page: int,
    max_pages: int,
    page: int,
    what_exclude: str | None = None,
) -> JobSyncRequest:
    criteria = page_request_diagnostics(
        provider_country=signature.provider_country,
        page=max(1, page),
        what=query_text,
        where=location.provider_where,
        what_exclude=what_exclude,
        results_per_page=bounded_results_per_page(results_per_page),
    )
    criteria.update(
        {
            "maxPages": max(1, max_pages),
            "displayLocation": location.display_location,
            "normalizedLocationKey": location.normalized_key,
            "jobLocationTargetId": location.target_id,
            "providerLocationMappingId": location.provider_mapping_id,
            "locationConfidence": location.provider_mapping_confidence or location.location_confidence,
            "locationVerificationStatus": location.provider_mapping_status,
            "syncKey": signature.sync_key,
        }
    )
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
        query_kind=query_kind,
        criteria_json=criteria,
    )


def apply_signature_refresh_result(signature: JobSyncSignature, result: JobSyncResult) -> None:
    now = datetime.now(UTC)
    signature.last_attempted_at = now
    signature.last_status = result.status
    signature.last_error = result.error
    if result.status == "completed" and result.error is None:
        signature.last_completed_at = now
        signature.last_raw_result_count = result.raw_result_count
        signature.last_normalized_count = result.normalized_count
        signature.last_created_count = result.created_count
        signature.last_updated_count = result.updated_count
