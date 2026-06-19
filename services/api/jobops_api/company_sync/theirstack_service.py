from __future__ import annotations

from dataclasses import replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..company_sources.theirstack.client import TheirStackCompanySearchClient
from ..company_sources.theirstack.models import TheirStackCompanySearchRequest
from ..company_sources.theirstack.service import TheirStackCompanyEnrichmentService
from ..db.models import CompanySyncSignature
from ..settings import Settings
from .models import CompanySyncRequest, CompanySyncResult
from .service import (
    apply_company_sync_signature_result,
    build_theirstack_company_sync_key,
    is_company_sync_fresh,
    record_company_sync_run,
    sanitize_company_sync_json,
)


def upsert_theirstack_company_sync_signature(
    session: Session,
    *,
    query_text: str,
    request: TheirStackCompanySearchRequest | None = None,
    query_kind: str = "manual",
    source: str = "cli",
    results_per_page: int = 25,
    max_pages: int = 1,
    freshness_hours: int = 168,
    enabled: bool = True,
    verification_status: str = "verified",
    created_by: str | None = None,
    criteria_json: dict[str, Any] | None = None,
) -> CompanySyncSignature:
    query = clean_query_text(query_text)
    if not query:
        raise ValueError("TheirStack company sync signatures require query_text.")
    effective_request = request or TheirStackCompanySearchRequest(company_name_partial_match_or=(query,))
    effective_request = replace(
        effective_request,
        limit=effective_request.limit if effective_request.limit is not None else max(1, results_per_page),
        max_pages=max(1, effective_request.max_pages if effective_request.max_pages is not None else max_pages),
    )
    request_body = effective_request.to_api_body(page=1)
    sync_key = build_theirstack_company_sync_key(query_kind, request_body)
    criteria = build_company_signature_criteria_json(
        sync_key=sync_key,
        query_text=query,
        query_kind=query_kind,
        request=effective_request,
        criteria_json=criteria_json or {},
    )
    signature = session.scalar(select(CompanySyncSignature).where(CompanySyncSignature.sync_key == sync_key))
    if signature is None:
        signature = CompanySyncSignature(sync_key=sync_key)
        session.add(signature)
    signature.provider_name = "theirstack"
    signature.provider_type = "company_source"
    signature.sync_kind = "company_search"
    signature.query_text = query
    signature.query_kind = query_kind
    signature.results_per_page = max(1, effective_request.limit or results_per_page)
    signature.max_pages = max(1, effective_request.max_pages or max_pages)
    signature.freshness_hours = max(1, freshness_hours)
    signature.enabled = bool(enabled and verification_status != "needs_review")
    signature.verification_status = verification_status
    signature.source = source
    signature.created_by = created_by
    signature.criteria_json = criteria
    session.flush()
    signature.criteria_json = {**criteria, "companySyncSignatureId": signature.id}
    session.flush()
    return signature


def load_theirstack_company_sync_signatures(
    session: Session,
    *,
    signature_ids: list[str] | None = None,
    enabled_only: bool = True,
    max_signatures: int | None = None,
) -> list[CompanySyncSignature]:
    statement = select(CompanySyncSignature).where(CompanySyncSignature.provider_name == "theirstack")
    if signature_ids:
        signatures_by_id = {
            signature.id: signature
            for signature in session.scalars(statement.where(CompanySyncSignature.id.in_(signature_ids))).all()
        }
        return [signatures_by_id[signature_id] for signature_id in signature_ids if signature_id in signatures_by_id]
    if enabled_only:
        statement = statement.where(
            CompanySyncSignature.enabled.is_(True),
            CompanySyncSignature.verification_status != "needs_review",
        )
    statement = statement.order_by(CompanySyncSignature.created_at.asc(), CompanySyncSignature.sync_key.asc())
    if max_signatures:
        statement = statement.limit(max(1, max_signatures))
    return list(session.scalars(statement).all())


def sync_theirstack_company_signatures(
    session: Session,
    *,
    settings: Settings,
    signature_ids: list[str] | None = None,
    enabled_only: bool = True,
    force: bool = False,
    freshness_hours: int | None = None,
    max_pages: int | None = None,
    max_signatures: int | None = None,
    client: TheirStackCompanySearchClient | None = None,
) -> list[CompanySyncResult]:
    signatures = load_theirstack_company_sync_signatures(
        session,
        signature_ids=signature_ids,
        enabled_only=enabled_only,
        max_signatures=max_signatures,
    )
    service = TheirStackCompanyEnrichmentService(session=session, settings=settings, client=client)
    results: list[CompanySyncResult] = []
    explicit_ids = bool(signature_ids)
    for signature in signatures:
        request = company_sync_request_for_signature(signature, max_pages=max_pages)
        if should_skip_signature(signature, explicit_ids=explicit_ids, force=force):
            result = CompanySyncResult(
                request=request,
                status="skipped",
                diagnostics_json={"skipReason": "signature_not_runnable", "verificationStatus": signature.verification_status},
            )
            record_company_sync_run(session, result)
            apply_company_sync_signature_result(signature, result)
            results.append(result)
            continue
        resolved_freshness = freshness_hours or signature.freshness_hours or settings.theirstack_company_sync_freshness_hours
        if not force and is_company_sync_fresh(session, signature.sync_key, freshness_hours=resolved_freshness):
            result = CompanySyncResult(
                request=request,
                status="skipped_fresh",
                diagnostics_json={"skipReason": "fresh", "freshnessHours": resolved_freshness},
            )
            record_company_sync_run(session, result)
            apply_company_sync_signature_result(signature, result)
            results.append(result)
            continue
        search_request = request_from_signature(signature, max_pages=max_pages)
        enrichment = service.search_and_upsert_companies(search_request, discovery_query=signature.query_text)
        diagnostics = enrichment.diagnostics or {}
        error = enrichment.error_message if enrichment.status in {"failed", "unavailable"} else None
        result = CompanySyncResult(
            request=request,
            status=enrichment.status if enrichment.status != "unavailable" else "skipped",
            raw_result_count=int(diagnostics.get("rawCompanyCount") or len(enrichment.normalized_companies)),
            normalized_count=len(enrichment.normalized_companies),
            created_count=int(diagnostics.get("canonicalCompanyCreatedCount") or 0),
            updated_count=int(diagnostics.get("canonicalCompanyUpdatedCount") or 0),
            duplicate_count=max(0, len(enrichment.normalized_companies) - len(enrichment.companies)),
            failed_normalization_count=max(
                0,
                int(diagnostics.get("rawCompanyCount") or 0) - len(enrichment.normalized_companies),
            ),
            error=error,
            diagnostics_json={
                **diagnostics,
                "companySourceCount": diagnostics.get("companySourceCount", len(enrichment.company_sources)),
                "companyIds": [company.id for company in enrichment.companies if hasattr(company, "id")],
                "companySourceIds": [source.id for source in enrichment.company_sources if hasattr(source, "id")],
            },
            company_ids=tuple(company.id for company in enrichment.companies if hasattr(company, "id")),
            company_source_ids=tuple(source.id for source in enrichment.company_sources if hasattr(source, "id")),
        )
        record_company_sync_run(session, result)
        apply_company_sync_signature_result(signature, result)
        results.append(result)
    session.flush()
    return results


def company_sync_request_for_signature(signature: CompanySyncSignature, *, max_pages: int | None = None) -> CompanySyncRequest:
    criteria = signature.criteria_json or {}
    if max_pages:
        criteria = {**criteria, "maxPagesOverride": max_pages}
    return CompanySyncRequest(
        company_sync_signature_id=signature.id,
        sync_key=signature.sync_key,
        provider_name=signature.provider_name,
        provider_type=signature.provider_type,
        sync_kind=signature.sync_kind,
        query_text=signature.query_text,
        query_kind=signature.query_kind,
        criteria_json=criteria,
    )


def request_from_signature(signature: CompanySyncSignature, *, max_pages: int | None = None) -> TheirStackCompanySearchRequest:
    criteria = signature.criteria_json or {}
    body = criteria.get("theirstackRequest")
    if not isinstance(body, dict):
        body = {}
    job_filters = body.get("job_filters") if isinstance(body.get("job_filters"), dict) else {}
    return TheirStackCompanySearchRequest(
        company_name_or=tuple(clean_values(body.get("company_name_or"))),
        company_name_partial_match_or=tuple(clean_values(body.get("company_name_partial_match_or"))),
        company_domain_or=tuple(clean_values(body.get("company_domain_or"))),
        company_country_code_or=tuple(clean_values(body.get("company_country_code_or"))),
        company_description_pattern_or=tuple(clean_values(body.get("company_description_pattern_or"))),
        company_technology_slug_or=tuple(clean_values(body.get("company_technology_slug_or"))),
        company_technology_slug_and=tuple(clean_values(body.get("company_technology_slug_and"))),
        company_keyword_slug_or=tuple(clean_values(body.get("company_keyword_slug_or"))),
        job_filters=job_filters,
        limit=int(body.get("limit") or signature.results_per_page or 25),
        page=1,
        max_pages=max(1, max_pages or int(body.get("maxPages") or body.get("max_pages") or signature.max_pages or 1)),
        include_total_results=bool(body.get("include_total_results", True)),
    )


def should_skip_signature(signature: CompanySyncSignature, *, explicit_ids: bool, force: bool) -> bool:
    if not signature.enabled:
        return True
    if signature.verification_status == "needs_review" and not (explicit_ids and force):
        return True
    return False


def build_company_signature_criteria_json(
    *,
    sync_key: str,
    query_text: str,
    query_kind: str,
    request: TheirStackCompanySearchRequest,
    criteria_json: dict[str, Any],
) -> dict[str, Any]:
    request_body = request.to_api_body(page=1)
    return sanitize_company_sync_json(
        {
            **criteria_json,
            "providerName": "theirstack",
            "providerType": "company_source",
            "syncKind": "company_search",
            "syncKey": sync_key,
            "queryText": query_text,
            "queryKind": query_kind,
            "theirstackRequest": request_body,
            "requestShape": request.sanitized_shape(),
            "resultsPerPage": request.limit,
            "maxPages": request.max_pages,
            "contentType": "application/json",
            "creditAwareness": "TheirStack may consume credits per returned company.",
        }
    )


def clean_values(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def clean_query_text(value: str | None) -> str:
    return " ".join((value or "").split()).strip()
