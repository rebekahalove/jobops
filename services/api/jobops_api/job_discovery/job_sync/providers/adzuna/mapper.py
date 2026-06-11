from __future__ import annotations

from sqlalchemy.orm import Session

from ....provider_utils import (
    clean_text_value,
    format_salary_text,
    html_to_text,
    infer_adzuna_currency_code,
    infer_remote_mode,
    nested_get,
    parse_datetime_value,
    parse_whole_currency_amount,
)
from ...location_country import normalize_provider_country_code
from ...location_resolver import resolve_or_create_job_location_from_provider_payload
from ...models import JobListingSourceRecord, JobSyncRequest, NormalizedJobListing
from .diagnostics import strip_secret_shaped_keys


def normalize_adzuna_job_record(
    raw: object,
    request: JobSyncRequest,
    *,
    session: Session,
) -> tuple[NormalizedJobListing, JobListingSourceRecord] | None:
    if not isinstance(raw, dict):
        return None
    title = clean_text_value(raw.get("title"))
    company_name = clean_text_value(nested_get(raw, "company", "display_name"))
    source_url = clean_text_value(raw.get("redirect_url"))
    if not title or not company_name or not source_url:
        return None
    provider_job_id = clean_text_value(raw["id"]) if "id" in raw else None
    if not provider_job_id:
        return None

    location_payload = raw.get("location") if isinstance(raw.get("location"), dict) else None
    provider_country = infer_adzuna_provider_country_from_location(location_payload) or normalize_provider_country_code(
        request.provider_country
    )
    salary_currency = infer_adzuna_currency_code(provider_country) if provider_country else None
    salary_min = parse_whole_currency_amount(raw.get("salary_min"))
    salary_max = parse_whole_currency_amount(raw.get("salary_max"))
    created = parse_datetime_value(raw.get("created"))
    full_description = html_to_text(str(raw.get("description") or "")) or None
    location_raw = clean_text_value(nested_get(raw, "location", "display_name"))
    location_target = resolve_or_create_job_location_from_provider_payload(
        session,
        provider_name="adzuna",
        raw_display_location=location_raw or request.display_location,
        provider_location_payload=location_payload,
        provider_country=provider_country,
    )
    listing = NormalizedJobListing(
        title=title,
        company_name=company_name,
        job_location_target_id=location_target.id,
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
        source_provider="adzuna",
        provider_type="broad_search",
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
    return strip_secret_shaped_keys(raw)


def infer_adzuna_provider_country_from_location(location_payload: object) -> str | None:
    if not isinstance(location_payload, dict):
        return None
    area = location_payload.get("area")
    if not isinstance(area, list) or not area:
        return None
    return normalize_provider_country_code(str(area[0]))
