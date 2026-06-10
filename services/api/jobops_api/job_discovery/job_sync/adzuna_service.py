from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.models import JobSyncSignature
from ...settings import Settings
from .location_country import normalize_provider_country_code
from .location_resolver import job_sync_location_from_mapping, resolve_provider_location_mapping
from .models import JobSyncRequest, JobSyncResult
from .providers.adzuna import AdzunaJobSyncProvider
from .providers.adzuna.client import bounded_results_per_page
from .providers.adzuna.provider import apply_signature_refresh_result
from .service import build_adzuna_sync_key, latest_completed_sync_at, record_job_sync_run


def upsert_adzuna_sync_signature(
    session: Session,
    *,
    query_text: str,
    display_location: str | None,
    provider_country: str | None = None,
    provider_where: str | None = None,
    query_kind: str = "manual",
    source: str = "cli",
    results_per_page: int = 50,
    max_pages: int = 1,
    freshness_hours: int = 24,
    enabled: bool = True,
    created_by: str | None = None,
) -> JobSyncSignature:
    query = clean_query_text(query_text)
    if not query:
        raise ValueError("Adzuna sync signatures require query_text.")
    country_hint = normalize_provider_country_code(provider_country)
    mapping = resolve_provider_location_mapping(
        session,
        provider_name="adzuna",
        display_location=display_location,
        default_provider_country=country_hint,
    )
    if country_hint:
        mapping.provider_country = country_hint
    if provider_where is not None:
        mapping.provider_where = provider_where.strip() or None
    location = job_sync_location_from_mapping(mapping.job_location_target, mapping)
    normalized_location_key = location.normalized_key or "any-location"
    resolved_country = normalize_provider_country_code(location.provider_country)
    verification_status = mapping.verification_status
    runnable = bool(resolved_country)
    signature_enabled = bool(enabled and runnable)
    if not runnable:
        signature_enabled = False
        verification_status = "needs_review"
    sync_key = (
        build_adzuna_sync_key(resolved_country, normalized_location_key, query)
        if resolved_country
        else build_adzuna_sync_key("unknown", normalized_location_key, query)
    )
    criteria_json = build_signature_criteria_json(
        sync_key=sync_key,
        provider_country=resolved_country,
        provider_where=location.provider_where,
        query_text=query,
        display_location=location.display_location,
        normalized_location_key=normalized_location_key,
        job_location_target_id=location.target_id,
        provider_location_mapping_id=location.provider_mapping_id,
        location_confidence=location.provider_mapping_confidence or location.location_confidence,
        location_verification_status=location.provider_mapping_status,
        results_per_page=results_per_page,
        max_pages=max_pages,
    )
    signature = session.scalar(select(JobSyncSignature).where(JobSyncSignature.sync_key == sync_key))
    if signature is None:
        signature = JobSyncSignature(sync_key=sync_key)
        session.add(signature)
    signature.provider_name = "adzuna"
    signature.provider_type = "broad_search"
    signature.sync_kind = "broad_search"
    signature.query_text = query
    signature.query_kind = query_kind
    signature.job_location_target_id = location.target_id
    signature.job_provider_location_mapping_id = location.provider_mapping_id
    signature.provider_country = resolved_country
    signature.provider_where = location.provider_where
    signature.display_location = location.display_location
    signature.normalized_location_key = normalized_location_key
    signature.results_per_page = bounded_results_per_page(results_per_page)
    signature.max_pages = max(1, max_pages)
    signature.freshness_hours = max(1, freshness_hours)
    signature.enabled = signature_enabled
    signature.verification_status = verification_status
    signature.source = source
    signature.created_by = created_by
    signature.criteria_json = criteria_json
    session.flush()
    signature.criteria_json = {**criteria_json, "jobSyncSignatureId": signature.id}
    session.flush()
    return signature


def sync_adzuna_signatures(
    session: Session,
    *,
    settings: Settings,
    signature_ids: list[str] | None = None,
    enabled_only: bool = True,
    force: bool = False,
    freshness_hours: int | None = None,
    max_pages: int | None = None,
) -> list[JobSyncResult]:
    signatures = load_adzuna_sync_signatures(
        session,
        signature_ids=signature_ids,
        enabled_only=enabled_only,
    )
    provider = AdzunaJobSyncProvider(
        app_id=settings.adzuna_app_id,
        app_key=settings.adzuna_app_key,
    )
    results: list[JobSyncResult] = []
    explicit_ids = bool(signature_ids)
    for signature in signatures:
        request = provider.build_sync_plan([signature], max_pages=max_pages).requests[0]
        if should_skip_signature(signature, explicit_ids=explicit_ids, force=force):
            result = JobSyncResult(
                request=request,
                status="skipped",
                diagnostics_json={
                    "skipReason": "signature_not_runnable",
                    "verificationStatus": signature.verification_status,
                    "providerCountry": signature.provider_country,
                },
            )
            record_job_sync_run(session, result)
            apply_signature_refresh_result(signature, result)
            results.append(result)
            continue
        resolved_freshness = freshness_hours or signature.freshness_hours or 24
        if not force and is_signature_fresh(session, signature, freshness_hours=resolved_freshness):
            latest_completed = signature.last_completed_at or latest_completed_sync_at(session, signature.sync_key)
            result = JobSyncResult(
                request=request,
                status="skipped_fresh",
                diagnostics_json={
                    "skipReason": "fresh",
                    "freshnessHours": resolved_freshness,
                    "latestCompletedAt": latest_completed.isoformat() if latest_completed else None,
                },
            )
            record_job_sync_run(session, result)
            apply_signature_refresh_result(signature, result)
            results.append(result)
            continue
        result = provider.refresh_inventory(session, request, freshness_hours=0, force=True)
        apply_signature_refresh_result(signature, result)
        results.append(result)
    session.flush()
    return results


def load_adzuna_sync_signatures(
    session: Session,
    *,
    signature_ids: list[str] | None,
    enabled_only: bool,
) -> list[JobSyncSignature]:
    statement = select(JobSyncSignature).where(JobSyncSignature.provider_name == "adzuna")
    if signature_ids:
        signatures_by_id = {
            signature.id: signature
            for signature in session.scalars(statement.where(JobSyncSignature.id.in_(signature_ids))).all()
        }
        return [signatures_by_id[signature_id] for signature_id in signature_ids if signature_id in signatures_by_id]
    elif enabled_only:
        statement = statement.where(JobSyncSignature.enabled.is_(True), JobSyncSignature.verification_status != "needs_review")
    return list(session.scalars(statement.order_by(JobSyncSignature.created_at.asc(), JobSyncSignature.sync_key.asc())).all())


def should_skip_signature(signature: JobSyncSignature, *, explicit_ids: bool, force: bool) -> bool:
    if not signature.enabled:
        return True
    if signature.verification_status == "needs_review" and not (explicit_ids and force):
        return True
    if not signature.provider_country:
        return True
    return False


def is_signature_fresh(session: Session, signature: JobSyncSignature, *, freshness_hours: int) -> bool:
    latest_completed = signature.last_completed_at or latest_completed_sync_at(session, signature.sync_key)
    if latest_completed is None:
        return False
    if latest_completed.tzinfo is None:
        latest_completed = latest_completed.replace(tzinfo=UTC)
    return latest_completed >= datetime.now(UTC) - timedelta(hours=freshness_hours)


def build_signature_criteria_json(
    *,
    sync_key: str,
    provider_country: str | None,
    provider_where: str | None,
    query_text: str,
    display_location: str | None,
    normalized_location_key: str | None,
    job_location_target_id: str | None,
    provider_location_mapping_id: str | None,
    location_confidence: str | None,
    location_verification_status: str | None,
    results_per_page: int,
    max_pages: int,
) -> dict[str, object]:
    api_path = f"/v1/api/jobs/{provider_country}/search/1" if provider_country else None
    return {
        "providerName": "adzuna",
        "providerCountry": provider_country,
        "apiPath": api_path,
        "what": query_text,
        "where": provider_where,
        "whatExclude": None,
        "resultsPerPage": bounded_results_per_page(results_per_page),
        "page": 1,
        "maxPages": max(1, max_pages),
        "contentType": "application/json",
        "syncKey": sync_key,
        "displayLocation": display_location,
        "normalizedLocationKey": normalized_location_key,
        "jobLocationTargetId": job_location_target_id,
        "providerLocationMappingId": provider_location_mapping_id,
        "locationConfidence": location_confidence,
        "locationVerificationStatus": location_verification_status,
    }


def clean_query_text(value: str | None) -> str:
    return " ".join((value or "").split()).strip()
