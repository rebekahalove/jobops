from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import CompanySyncRun, CompanySyncSignature
from ..job_discovery.job_sync.service import normalize_sync_key_text
from .models import CompanySyncRequest, CompanySyncResult


SENSITIVE_COMPANY_SYNC_KEY_PARTS = ("key", "token", "secret", "authorization", "cookie", "password", "bearer")


def build_theirstack_company_sync_key(query_kind: str, request_shape: dict[str, Any]) -> str:
    compact = json.dumps(sanitize_company_sync_json(request_shape), sort_keys=True, separators=(",", ":"), default=str)
    return f"theirstack:company:{normalize_sync_key_text(query_kind)}:{normalize_sync_key_text(compact)[:180]}"


def is_company_sync_fresh(session: Session, sync_key: str, *, freshness_hours: int) -> bool:
    latest_completed = latest_completed_company_sync_at(session, sync_key)
    if latest_completed is None:
        return False
    if latest_completed.tzinfo is None:
        latest_completed = latest_completed.replace(tzinfo=UTC)
    return latest_completed >= datetime.now(UTC) - timedelta(hours=max(1, freshness_hours))


def latest_completed_company_sync_at(session: Session, sync_key: str) -> datetime | None:
    return session.scalar(
        select(CompanySyncRun.completed_at)
        .where(
            CompanySyncRun.sync_key == sync_key,
            CompanySyncRun.status == "completed",
            CompanySyncRun.completed_at.is_not(None),
        )
        .order_by(CompanySyncRun.completed_at.desc())
        .limit(1)
    )


def record_company_sync_run(session: Session, result: CompanySyncResult) -> CompanySyncRun:
    request = result.request
    now = datetime.now(UTC)
    run = CompanySyncRun(
        company_sync_signature_id=request.company_sync_signature_id,
        sync_key=request.sync_key,
        provider_name=request.provider_name,
        provider_type=request.provider_type,
        sync_kind=request.sync_kind,
        query_text=request.query_text,
        query_kind=request.query_kind,
        criteria_json=sanitize_company_sync_json(request.criteria_json),
        status="failed" if result.error else result.status,
        started_at=now,
        completed_at=now,
        raw_result_count=result.raw_result_count,
        normalized_count=result.normalized_count,
        created_count=result.created_count,
        updated_count=result.updated_count,
        duplicate_count=result.duplicate_count,
        failed_normalization_count=result.failed_normalization_count,
        error=result.error,
        diagnostics_json=sanitize_company_sync_json(result.diagnostics_json),
    )
    session.add(run)
    session.flush()
    return run


def apply_company_sync_signature_result(signature: CompanySyncSignature, result: CompanySyncResult) -> None:
    now = datetime.now(UTC)
    signature.last_attempted_at = now
    signature.last_status = "failed" if result.error else result.status
    signature.last_error = result.error
    if result.status == "completed" and result.error is None:
        signature.last_completed_at = now
        signature.last_raw_result_count = result.raw_result_count
        signature.last_normalized_count = result.normalized_count
        signature.last_created_count = result.created_count
        signature.last_updated_count = result.updated_count


def sanitize_company_sync_json(value: Any, *, max_list_items: int = 50, max_string_chars: int = 1000) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if any(part in key_text.casefold() for part in SENSITIVE_COMPANY_SYNC_KEY_PARTS):
                continue
            sanitized[key_text] = sanitize_company_sync_json(item, max_list_items=max_list_items, max_string_chars=max_string_chars)
        return sanitized
    if isinstance(value, (list, tuple, set)):
        return [
            sanitize_company_sync_json(item, max_list_items=max_list_items, max_string_chars=max_string_chars)
            for item in list(value)[:max_list_items]
        ]
    if isinstance(value, str):
        return value[:max_string_chars]
    return value


def request_summary_from_signature(signature: CompanySyncSignature) -> CompanySyncRequest:
    return CompanySyncRequest(
        company_sync_signature_id=signature.id,
        sync_key=signature.sync_key,
        provider_name=signature.provider_name,
        provider_type=signature.provider_type,
        sync_kind=signature.sync_kind,
        query_text=signature.query_text,
        query_kind=signature.query_kind,
        criteria_json=signature.criteria_json or {},
    )
