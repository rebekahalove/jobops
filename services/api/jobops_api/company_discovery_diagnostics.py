from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .db.models import CompanyDiscoveryProviderCall, CompanyDiscoveryRun


SENSITIVE_DIAGNOSTIC_KEY_PARTS = ("key", "token", "secret", "authorization", "cookie", "password", "bearer")
MAX_DIAGNOSTIC_STRING_CHARS = 500
MAX_DIAGNOSTIC_LIST_ITEMS = 24
MAX_DIAGNOSTIC_DICT_ITEMS = 40


def start_company_discovery_run(
    session: Session,
    *,
    candidate_profile_id: str,
    command_text: str,
    router_action: str | None = None,
    router_confidence: str | None = None,
    target_workspace: str | None = None,
    source_path: str = "unknown",
) -> CompanyDiscoveryRun:
    now = datetime.now(timezone.utc)
    run = CompanyDiscoveryRun(
        candidate_profile_id=candidate_profile_id,
        command_text=command_text,
        status="running",
        source_path=source_path,
        router_action=router_action,
        router_confidence=router_confidence,
        target_workspace=target_workspace,
        started_at=now,
    )
    session.add(run)
    session.flush()
    return run


def update_company_discovery_run(
    session: Session,
    run_id: str | None,
    **values: Any,
) -> CompanyDiscoveryRun | None:
    run = get_company_discovery_run(session, run_id)
    if run is None:
        return None
    for key, value in values.items():
        if not hasattr(run, key):
            continue
        if key == "run_diagnostics_json" and isinstance(value, dict):
            value = sanitize_diagnostic_value(value)
        setattr(run, key, value)
    session.add(run)
    session.flush()
    return run


def complete_company_discovery_run(
    session: Session,
    run_id: str | None,
    **values: Any,
) -> CompanyDiscoveryRun | None:
    return update_company_discovery_run(
        session,
        run_id,
        status=values.pop("status", "completed"),
        completed_at=values.pop("completed_at", datetime.now(timezone.utc)),
        **values,
    )


def fail_company_discovery_run(
    session: Session,
    run_id: str | None,
    *,
    error: str | None = None,
    **values: Any,
) -> CompanyDiscoveryRun | None:
    return complete_company_discovery_run(session, run_id, status="failed", error=truncate_string(error) if error else None, **values)


def record_company_discovery_provider_call(
    session: Session,
    *,
    company_discovery_run_id: str | None,
    stage: str,
    provider: str,
    status: str,
    label: str,
    request_summary: dict[str, Any] | None = None,
    result_summary: dict[str, Any] | None = None,
    error: str | dict[str, Any] | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> CompanyDiscoveryProviderCall | None:
    if not company_discovery_run_id:
        return None
    now = datetime.now(timezone.utc)
    call = CompanyDiscoveryProviderCall(
        company_discovery_run_id=company_discovery_run_id,
        stage=stage,
        provider=provider,
        status=status,
        label=label,
        request_summary_json=sanitize_diagnostic_summary(request_summary or {}),
        result_summary_json=sanitize_diagnostic_summary(result_summary or {}),
        error_json=sanitize_error(error),
        started_at=started_at or now if status in {"started", "completed", "failed"} else started_at,
        completed_at=completed_at or now if status in {"completed", "failed", "skipped", "unavailable"} else completed_at,
    )
    session.add(call)
    session.flush()
    return call


def update_company_discovery_provider_call(
    session: Session,
    call: CompanyDiscoveryProviderCall | None,
    *,
    status: str,
    request_summary: dict[str, Any] | None = None,
    result_summary: dict[str, Any] | None = None,
    error: str | dict[str, Any] | None = None,
    completed_at: datetime | None = None,
) -> CompanyDiscoveryProviderCall | None:
    if call is None:
        return None
    call.status = status
    if request_summary is not None:
        call.request_summary_json = sanitize_diagnostic_summary({**(call.request_summary_json or {}), **request_summary})
    if result_summary is not None:
        call.result_summary_json = sanitize_diagnostic_summary(result_summary)
    if error is not None:
        call.error_json = sanitize_error(error)
    if status in {"completed", "failed", "skipped", "unavailable"}:
        call.completed_at = completed_at or datetime.now(timezone.utc)
    session.add(call)
    session.flush()
    return call


def get_company_discovery_run(session: Session, run_id: str | None) -> CompanyDiscoveryRun | None:
    if not run_id:
        return None
    return session.get(CompanyDiscoveryRun, run_id)


def latest_company_discovery_run(session: Session, *, candidate_profile_id: str) -> CompanyDiscoveryRun | None:
    return session.scalar(
        select(CompanyDiscoveryRun)
        .where(CompanyDiscoveryRun.candidate_profile_id == candidate_profile_id)
        .options(selectinload(CompanyDiscoveryRun.provider_calls))
        .order_by(CompanyDiscoveryRun.created_at.desc())
        .limit(1)
    )


def owned_company_discovery_run(session: Session, *, run_id: str, candidate_profile_id: str) -> CompanyDiscoveryRun | None:
    return session.scalar(
        select(CompanyDiscoveryRun)
        .where(CompanyDiscoveryRun.id == run_id, CompanyDiscoveryRun.candidate_profile_id == candidate_profile_id)
        .options(selectinload(CompanyDiscoveryRun.provider_calls))
        .limit(1)
    )


def serialize_company_discovery_run_status(run: CompanyDiscoveryRun) -> dict[str, Any]:
    diagnostics = run.run_diagnostics_json if isinstance(run.run_diagnostics_json, dict) else {}
    return {
        "id": run.id,
        "status": run.status or "unknown",
        "createdAt": isoformat(run.created_at),
        "startedAt": isoformat(run.started_at),
        "completedAt": isoformat(run.completed_at),
        "commandPreview": command_preview(run.command_text),
        "sourcePath": run.source_path or "unknown",
        "routerAction": run.router_action or "unknown",
        "routerConfidence": run.router_confidence or "unknown",
        "companyDiscoveryPreflightBlocked": bool(run.company_discovery_preflight_blocked),
        "preflightReason": run.preflight_reason,
        "sourceProvider": run.source_provider or "unknown",
        "searchGroundingEnabled": run.search_grounding_enabled,
        "modelProvider": run.model_provider,
        "modelName": run.model_name,
        "savedCompanyCount": run.saved_company_count or 0,
        "linkedCompanyCount": run.linked_company_count or 0,
        "duplicateCompanyCount": run.duplicate_company_count or 0,
        "skippedCompanyCount": run.skipped_company_count or 0,
        "zeroNewCompanyReason": run.zero_new_company_reason,
        "searchQueriesUsed": string_list(diagnostics.get("searchQueriesUsed")),
        "discoveryAngles": string_list(diagnostics.get("discoveryAngles")),
        "theirStack": dict_value(diagnostics.get("theirStack")),
        "firstPartySync": dict_value(diagnostics.get("firstPartySync")),
        "providerDiagnostics": [serialize_provider_call(call) for call in sorted(run.provider_calls, key=provider_call_order_key)],
        "companies": list_of_dicts(diagnostics.get("companies")),
        "diagnosticMessages": string_list(diagnostics.get("diagnosticMessages")),
    }


def serialize_provider_call(call: CompanyDiscoveryProviderCall) -> dict[str, Any]:
    return {
        "stage": call.stage or "unknown",
        "provider": call.provider or "unknown",
        "status": call.status or "unknown",
        "label": call.label or "Provider call",
        "startedAt": isoformat(call.started_at),
        "completedAt": isoformat(call.completed_at),
        "requestSummary": sanitize_diagnostic_summary(call.request_summary_json or {}),
        "resultSummary": sanitize_diagnostic_summary(call.result_summary_json or {}),
        "error": sanitize_diagnostic_value(call.error_json or {}) if call.error_json else None,
    }


def sanitize_diagnostic_summary(value: dict[str, Any]) -> dict[str, Any]:
    sanitized = sanitize_diagnostic_value(value)
    return sanitized if isinstance(sanitized, dict) else {}


def sanitize_error(value: str | dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        return {"message": truncate_string(value)}
    sanitized = sanitize_diagnostic_value(value)
    return sanitized if isinstance(sanitized, dict) else {"message": truncate_string(str(value))}


def sanitize_diagnostic_value(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_DIAGNOSTIC_DICT_ITEMS:
                sanitized["truncated"] = True
                break
            key_text = str(key)
            if any(part in key_text.casefold() for part in SENSITIVE_DIAGNOSTIC_KEY_PARTS):
                continue
            sanitized[key_text] = sanitize_diagnostic_value(item)
        return sanitized
    if isinstance(value, list | tuple):
        items = [sanitize_diagnostic_value(item) for item in list(value)[:MAX_DIAGNOSTIC_LIST_ITEMS]]
        if len(value) > MAX_DIAGNOSTIC_LIST_ITEMS:
            items.append(f"... {len(value) - MAX_DIAGNOSTIC_LIST_ITEMS} more")
        return items
    if isinstance(value, str):
        return truncate_string(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return truncate_string(str(value))


def truncate_string(value: str | None) -> str:
    text = value or ""
    return text if len(text) <= MAX_DIAGNOSTIC_STRING_CHARS else f"{text[:MAX_DIAGNOSTIC_STRING_CHARS]}..."


def provider_call_order_key(call: CompanyDiscoveryProviderCall) -> tuple[datetime, str]:
    return (call.created_at or call.started_at or datetime.min.replace(tzinfo=timezone.utc), call.id)


def isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def command_preview(value: str | None, *, limit: int = 220) -> str | None:
    if not value:
        return None
    return " ".join(value.split())[:limit]


def string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
