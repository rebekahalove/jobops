from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ....ashby_utils import canonical_ashby_board_url
from ....provider_utils import clean_text_value, html_to_text, infer_remote_mode, parse_datetime_value
from ...location_resolver import resolve_or_create_job_location_from_provider_payload
from ...models import JobListingSourceRecord, JobSyncRequest, NormalizedJobListing


def normalize_ashby_job_record(
    raw: object,
    request: JobSyncRequest,
    *,
    session: Session,
) -> tuple[NormalizedJobListing, JobListingSourceRecord] | None:
    if not isinstance(raw, dict) or not request.ats_board_token:
        return None
    provider_job_id = clean_text_value(raw.get("id") or raw.get("jobId"))
    title = clean_text_value(raw.get("title") or raw.get("name"))
    company_name = request.company_name or clean_text_value(raw.get("companyName")) or request.ats_board_token.replace("-", " ").replace("_", " ").title()
    if not provider_job_id or not title or not company_name:
        return None
    source_url = ashby_job_url(raw, org_slug=request.ats_board_token, provider_job_id=provider_job_id)
    if not source_url:
        return None
    location_raw = ashby_location(raw)
    location_payload = raw.get("location") if isinstance(raw.get("location"), dict) else None
    location_target = resolve_or_create_job_location_from_provider_payload(
        session,
        provider_name="ashby",
        raw_display_location=location_raw,
        provider_location_payload=location_payload,
        provider_country=request.provider_country,
    )
    html_description = clean_text_value(
        raw.get("descriptionHtml")
        or raw.get("description_html")
        or raw.get("description")
        or raw.get("content")
    )
    full_description = html_to_text(html_description or "") or html_description
    source_updated_at = parse_datetime_value(
        raw.get("updatedAt")
        or raw.get("updated_at")
        or raw.get("publishedAt")
        or raw.get("published_at")
        or raw.get("createdAt")
        or raw.get("created_at")
    )
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
        remote_work_mode=ashby_remote_mode(raw) or infer_remote_mode(f"{title} {location_raw or ''} {full_description or ''}"),
        employment_type=clean_text_value(raw.get("employmentType") or raw.get("employment_type") or raw.get("jobType")),
        salary_text=ashby_compensation_text(raw),
        full_description=full_description,
        description_excerpt=full_description[:600] if full_description else None,
        source_updated_at=source_updated_at,
        source_status="active" if not ashby_job_is_closed(raw) else "closed",
    )
    raw_metadata = dict(raw)
    raw_metadata["ashbyBoardUrl"] = canonical_ashby_board_url(request.ats_board_token)
    raw_metadata["ashbyOrgSlug"] = request.ats_board_token
    raw_metadata["ashbyProviderJobId"] = provider_job_id
    source_result_id = f"{request.ats_board_token}:{provider_job_id}"
    source = JobListingSourceRecord(
        source_provider="ashby",
        provider_type="ats_board",
        provider_job_id=source_result_id,
        source_result_id=source_result_id,
        ats_provider="ashby",
        ats_board_token=request.ats_board_token,
        source_url=source_url,
        apply_url=source_url,
        canonical_url=source_url,
        source_query=request.query_text,
        source_location=request.display_location,
        source_country=request.provider_country,
        raw_location=location_raw,
        raw_metadata_json=raw_metadata,
        source_updated_at=source_updated_at,
        source_status=listing.source_status,
    )
    return listing, source


def ashby_job_url(raw: dict[str, Any], *, org_slug: str, provider_job_id: str) -> str | None:
    for key in ("jobUrl", "job_url", "url", "externalUrl", "applicationUrl"):
        value = clean_text_value(raw.get(key))
        if value and value.startswith(("http://", "https://")):
            return value
    return f"{canonical_ashby_board_url(org_slug)}/{provider_job_id}"


def ashby_location(raw: dict[str, Any]) -> str | None:
    for key in ("locationName", "location_name", "location", "address", "office"):
        value = raw.get(key)
        if isinstance(value, str):
            cleaned = clean_text_value(value)
            if cleaned:
                return cleaned
        if isinstance(value, dict):
            for nested_key in ("name", "displayName", "city", "region", "country"):
                cleaned = clean_text_value(value.get(nested_key))
                if cleaned:
                    return cleaned
    return None


def ashby_remote_mode(raw: dict[str, Any]) -> str | None:
    for key in ("remote", "isRemote"):
        if raw.get(key) is True:
            return "remote"
        if raw.get(key) is False:
            return None
    return None


def ashby_compensation_text(raw: dict[str, Any]) -> str | None:
    for key in ("compensation", "compensationTierSummary", "salary", "salaryRange"):
        value = raw.get(key)
        if isinstance(value, str):
            cleaned = clean_text_value(value)
            if cleaned:
                return cleaned
        if isinstance(value, dict):
            cleaned = clean_text_value(value.get("display") or value.get("summary") or value.get("text"))
            if cleaned:
                return cleaned
    return None


def ashby_job_is_closed(raw: dict[str, Any]) -> bool:
    status = clean_text_value(raw.get("status") or raw.get("state"))
    return bool(status and status.casefold() in {"closed", "archived", "inactive"})
