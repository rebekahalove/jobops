from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.models import JobListing, JobListingSource, JobSyncRun
from .models import JobListingSourceRecord, JobListingUpsertResult, JobSyncRequest, JobSyncResult, NormalizedJobListing


SECRET_CRITERIA_KEYS = {
    "app_id",
    "appId",
    "app_key",
    "appKey",
    "authorization",
    "cookie",
    "cookies",
    "session",
    "session_cookie",
    "token",
}


def normalize_sync_key_text(value: str | None) -> str:
    cleaned = " ".join((value or "").split()).strip().casefold()
    cleaned = re.sub(r"[^a-z0-9._:-]+", "-", cleaned)
    return cleaned.strip("-") or "any"


def build_greenhouse_sync_key(board_token: str) -> str:
    return f"greenhouse:board:{normalize_sync_key_text(board_token)}"


def build_adzuna_sync_key(provider_country: str, location_key: str | None, query_text: str | None) -> str:
    country = normalize_sync_key_text(provider_country)
    location = normalize_sync_key_text(location_key)
    query = normalize_sync_key_text(query_text)
    return f"adzuna:broad:{country}:{location}:{query}"


def is_sync_fresh(session: Session, sync_key: str, *, freshness_hours: int = 24) -> bool:
    latest_completed = latest_completed_sync_at(session, sync_key)
    if latest_completed is None:
        return False
    if latest_completed.tzinfo is None:
        latest_completed = latest_completed.replace(tzinfo=UTC)
    return latest_completed >= datetime.now(UTC) - timedelta(hours=freshness_hours)


def latest_completed_sync_at(session: Session, sync_key: str) -> datetime | None:
    return session.scalar(
        select(JobSyncRun.completed_at)
        .where(JobSyncRun.sync_key == sync_key, JobSyncRun.status == "completed", JobSyncRun.completed_at.is_not(None))
        .order_by(JobSyncRun.completed_at.desc())
        .limit(1)
    )


def upsert_job_listing_from_provider_record(
    session: Session,
    *,
    listing: NormalizedJobListing,
    source: JobListingSourceRecord,
) -> JobListingUpsertResult:
    existing_source = find_existing_job_listing_source(session, source)
    now = datetime.now(UTC)
    if existing_source is None:
        job_listing = JobListing()
        created = True
        updated = False
        session.add(job_listing)
    else:
        job_listing = existing_source.job_listing
        created = False
        updated = True

    apply_listing_fields(job_listing, listing, synced_at=now)
    if existing_source is None:
        existing_source = JobListingSource(
            job_listing=job_listing,
            source_provider=source.source_provider,
            provider_type=str(source.provider_type),
        )
        session.add(existing_source)
    apply_source_fields(existing_source, source, synced_at=now)
    session.flush()
    return JobListingUpsertResult(
        job_listing_id=job_listing.id,
        job_listing_source_id=existing_source.id,
        created=created,
        updated=updated,
    )


def find_existing_job_listing_source(session: Session, source: JobListingSourceRecord) -> JobListingSource | None:
    provider = source.source_provider
    provider_job_id = clean_identity_value(source.provider_job_id)
    ats_board_token = clean_identity_value(source.ats_board_token)

    if provider == "greenhouse" and ats_board_token and provider_job_id:
        return session.scalar(
            select(JobListingSource).where(
                JobListingSource.source_provider == provider,
                JobListingSource.ats_board_token == ats_board_token,
                JobListingSource.provider_job_id == provider_job_id,
            )
        )
    if provider_job_id:
        return session.scalar(
            select(JobListingSource).where(
                JobListingSource.source_provider == provider,
                JobListingSource.provider_job_id == provider_job_id,
            )
        )
    raise ValueError("Provider record must include a stable provider job id.")


def record_job_sync_run(session: Session, result: JobSyncResult) -> JobSyncRun:
    request = result.request
    run = JobSyncRun(
        job_sync_signature_id=request.job_sync_signature_id,
        sync_key=request.sync_key,
        provider_name=request.provider_name,
        provider_type=str(request.provider_type),
        sync_kind=str(request.sync_kind),
        company_id=request.company_id,
        company_name=request.company_name,
        ats_provider=request.ats_provider,
        ats_board_token=request.ats_board_token,
        provider_country=request.provider_country,
        target_country=request.target_country,
        target_location_kind=request.target_location_kind,
        display_location=request.display_location,
        provider_where=request.provider_where,
        query_text=request.query_text,
        query_kind=request.query_kind,
        criteria_json=sanitize_criteria_json({**request.criteria_json, **result.diagnostics_json}),
        status="failed" if result.error else result.status,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        raw_result_count=result.raw_result_count,
        normalized_count=result.normalized_count,
        created_count=result.created_count,
        updated_count=result.updated_count,
        closed_count=result.closed_count,
        failed_normalization_count=result.failed_normalization_count,
        error=result.error,
    )
    session.add(run)
    session.flush()
    return run


def sanitize_criteria_json(criteria: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in criteria.items():
        if key in SECRET_CRITERIA_KEYS or key.casefold() in {secret.casefold() for secret in SECRET_CRITERIA_KEYS}:
            continue
        if isinstance(value, dict):
            sanitized[key] = sanitize_criteria_json(value)
        else:
            sanitized[key] = value
    return sanitized


def apply_listing_fields(job_listing: JobListing, listing: NormalizedJobListing, *, synced_at: datetime) -> None:
    for name in (
        "title",
        "job_location_target_id",
        "company_id",
        "company_name",
        "canonical_url",
        "apply_url",
        "source_url",
        "location_raw",
        "location_display",
        "location_city",
        "location_region",
        "location_country",
        "location_metro",
        "location_confidence",
        "remote_work_mode",
        "employment_type",
        "salary_min",
        "salary_max",
        "salary_currency",
        "salary_text",
        "description_excerpt",
        "full_description",
        "posting_date",
        "source_updated_at",
        "source_status",
    ):
        setattr(job_listing, name, getattr(listing, name))
    job_listing.last_seen_at = synced_at
    job_listing.last_synced_at = synced_at
    job_listing.is_active = listing.source_status not in {"closed", "expired", "inactive"}
    if job_listing.is_active:
        job_listing.closed_at = None
        job_listing.close_reason = None
    elif job_listing.closed_at is None:
        job_listing.closed_at = synced_at
        job_listing.close_reason = listing.source_status


def apply_source_fields(job_listing_source: JobListingSource, source: JobListingSourceRecord, *, synced_at: datetime) -> None:
    for name in (
        "source_provider",
        "provider_type",
        "provider_job_id",
        "source_result_id",
        "ats_provider",
        "ats_board_token",
        "source_url",
        "apply_url",
        "canonical_url",
        "source_query",
        "source_location",
        "source_country",
        "raw_location",
        "raw_metadata_json",
    ):
        setattr(job_listing_source, name, getattr(source, name))
    for name in (
        "application_fields_json",
        "application_requirements_json",
        "pay_transparency_json",
    ):
        value = getattr(source, name)
        if value is not None:
            setattr(job_listing_source, name, value)
    job_listing_source.source_updated_at = source.source_updated_at
    job_listing_source.last_seen_at = synced_at
    job_listing_source.last_synced_at = synced_at
    job_listing_source.is_active = source.source_status not in {"closed", "expired", "inactive"}
    if job_listing_source.is_active:
        job_listing_source.closed_at = None
        job_listing_source.close_reason = None
    elif job_listing_source.closed_at is None:
        job_listing_source.closed_at = synced_at
        job_listing_source.close_reason = source.source_status


def clean_identity_value(value: str | None) -> str | None:
    cleaned = str(value).strip() if value is not None else ""
    return cleaned or None
