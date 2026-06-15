from __future__ import annotations

from sqlalchemy.orm import Session

from ....provider_utils import clean_text_value, html_to_text, infer_remote_mode, nested_get, parse_datetime_value
from ...location_resolver import resolve_or_create_job_location_from_provider_payload
from ...models import JobListingSourceRecord, JobSyncRequest, NormalizedJobListing
from .application_fields import (
    extract_application_fields_from_greenhouse_payload,
    extract_pay_transparency_from_greenhouse_payload,
    summarize_greenhouse_application_requirements,
)
from .models import GreenhouseDetailFetchResult


def merge_greenhouse_job_payloads(result: GreenhouseDetailFetchResult) -> dict[str, object]:
    merged = {**result.list_job, **(result.retrieve_job or {})}
    merged["job_board_list_payload"] = result.list_job
    merged["job_board_retrieve_payload"] = result.retrieve_job
    if result.retrieve_request is not None:
        merged["job_board_retrieve_request"] = result.retrieve_request
    if result.retrieve_error is not None:
        merged["job_board_retrieve_error"] = result.retrieve_error
    if result.retrieve_skipped is not None:
        merged["job_board_retrieve_skipped"] = result.retrieve_skipped
    return merged


def normalize_greenhouse_job_record(
    raw: object,
    request: JobSyncRequest,
    *,
    session: Session,
) -> tuple[NormalizedJobListing, JobListingSourceRecord] | None:
    if not isinstance(raw, dict) or not request.ats_board_token:
        return None
    title = clean_text_value(raw.get("title"))
    source_url = clean_text_value(raw.get("absolute_url"))
    provider_job_id = clean_text_value(raw.get("id"))
    company_name = request.company_name or request.ats_board_token.replace("-", " ").replace("_", " ").title()
    if not title or not company_name or not source_url or not provider_job_id:
        return None
    full_description = html_to_text(str(raw.get("content") or "")) or None
    location_raw = clean_text_value(nested_get(raw, "location", "name"))
    location_payload = raw.get("location") if isinstance(raw.get("location"), dict) else None
    location_target = resolve_or_create_job_location_from_provider_payload(
        session,
        provider_name="greenhouse",
        raw_display_location=location_raw,
        provider_location_payload=location_payload,
        provider_country=request.provider_country,
    )
    source_updated_at = parse_datetime_value(raw.get("updated_at"))
    listing = NormalizedJobListing(
        title=title,
        company_name=company_name,
        job_location_target_id=location_target.id,
        company_id=request.company_id,
        canonical_url=source_url,
        apply_url=source_url,
        source_url=source_url,
        location_raw=location_raw,
        location_display=location_target.display_name or location_raw,
        location_city=location_target.city,
        location_region=location_target.region,
        location_country=location_target.country_code,
        location_metro=location_target.city,
        location_confidence=location_target.confidence,
        remote_work_mode=infer_remote_mode(f"{title} {full_description or ''}"),
        full_description=full_description,
        description_excerpt=full_description[:600] if full_description else None,
        source_updated_at=source_updated_at,
        source_status="active",
    )
    raw_metadata = copy_greenhouse_raw_metadata(raw)
    source_result_id = f"{request.ats_board_token}:{provider_job_id}" if provider_job_id else None
    application_metadata = {
        **raw_metadata,
        "ats_board_token": request.ats_board_token,
        "source_result_id": source_result_id,
    }
    application_fields = extract_application_fields_from_greenhouse_payload(application_metadata)
    application_requirements = summarize_greenhouse_application_requirements(application_fields)
    pay_transparency = extract_pay_transparency_from_greenhouse_payload(application_metadata)
    source = JobListingSourceRecord(
        source_provider="greenhouse",
        provider_type="ats_board",
        provider_job_id=provider_job_id,
        source_result_id=source_result_id,
        ats_provider="greenhouse",
        ats_board_token=request.ats_board_token,
        source_url=source_url,
        apply_url=source_url,
        canonical_url=source_url,
        source_query=request.query_text,
        source_location=request.display_location,
        source_country=request.provider_country,
        raw_location=location_raw,
        raw_metadata_json=raw_metadata,
        application_fields_json=application_fields,
        application_requirements_json=application_requirements,
        pay_transparency_json=pay_transparency,
        source_updated_at=source_updated_at,
        source_status="active",
    )
    return listing, source


def copy_greenhouse_raw_metadata(raw: dict[str, object]) -> dict[str, object]:
    return dict(raw)
