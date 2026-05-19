from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from .company_discovery import normalize_company_name, serialize_company
from .db.models import CandidateProfile, TargetCompany


CompanyUpdateField = Literal["website_url", "careers_url", "job_listings_url", "source_urls", "notes"]
CompanyUpdateStatus = Literal["completed", "needs_confirmation", "failed"]

ALLOWED_COMPANY_UPDATE_FIELDS: set[str] = {"website_url", "careers_url", "job_listings_url", "source_urls", "notes"}
URL_COMPANY_UPDATE_FIELDS: set[str] = {"website_url", "careers_url", "job_listings_url", "source_urls"}


@dataclass(frozen=True)
class CompanyUpdateRequest:
    company_id: str | None
    company_name: str | None
    field: str | None
    url: str | None = None
    raw_text: str | None = None


@dataclass(frozen=True)
class CompanyUpdateResult:
    status: CompanyUpdateStatus
    assistant_message: str
    body: dict[str, Any]


def run_company_update(
    request: CompanyUpdateRequest,
    *,
    candidate_profile: CandidateProfile,
    db_session: Session,
) -> CompanyUpdateResult:
    field = clean_text(request.field)
    if field not in ALLOWED_COMPANY_UPDATE_FIELDS:
        return failed_result(
            "Unsupported company update field.",
            "unsupported_company_update_field",
            {"field": request.field, "allowedFields": sorted(ALLOWED_COMPANY_UPDATE_FIELDS)},
        )

    company_match = resolve_company_for_update(
        db_session,
        candidate_profile=candidate_profile,
        company_id=clean_text(request.company_id),
        company_name=clean_text(request.company_name),
    )
    if company_match.status != "completed":
        return company_match

    company = company_match.body["companyRow"]
    assert isinstance(company, TargetCompany)

    if field in URL_COMPANY_UPDATE_FIELDS:
        url = normalize_http_url(request.url)
        if url is None:
            return failed_result(
                "A valid http(s) URL is required for that company update.",
                "company_update_url_required",
                {"field": field},
            )
        result = apply_url_update(company, field, url)
    else:
        note_text = clean_text(request.raw_text)
        if note_text is None:
            return failed_result(
                "A note value is required for that company update.",
                "company_update_note_required",
                {"field": field},
            )
        previous = company.notes or ""
        company.notes = note_text
        result = {
            "updatedField": field,
            "previousValue": previous,
            "newValue": company.notes,
            "changed": previous != company.notes,
        }

    db_session.add(company)
    db_session.commit()
    db_session.refresh(company)

    field_label = field.replace("_", " ")
    return CompanyUpdateResult(
        status="completed",
        assistant_message=f"Updated {company.name}'s {field_label}.",
        body={
            "ok": True,
            "result": {
                "assistantMessage": f"Updated {company.name}'s {field_label}.",
                "company": serialize_company(company),
                **result,
            },
        },
    )


def resolve_company_for_update(
    session: Session,
    *,
    candidate_profile: CandidateProfile,
    company_id: str | None,
    company_name: str | None,
) -> CompanyUpdateResult:
    if company_id:
        company = session.get(TargetCompany, company_id)
        if company is None or company.candidate_profile_id != candidate_profile.id:
            return clarification_result(
                "I do not see that company in your tracked companies yet. Do you want me to add it as a new company to follow, or did you mean a different tracked company?",
                "company_not_found",
                {"companyId": company_id},
            )
        return matched_company_result(company)

    normalized_name = normalize_company_name(company_name)
    if not normalized_name:
        return clarification_result(
            "Which tracked company should I update?",
            "company_update_target_required",
            {},
        )

    matches = list(
        session.scalars(
            select(TargetCompany).where(
                TargetCompany.candidate_profile_id == candidate_profile.id,
                TargetCompany.normalized_name == normalized_name,
            )
        )
    )
    if not matches:
        matches = [
            company
            for company in session.scalars(
                select(TargetCompany).where(TargetCompany.candidate_profile_id == candidate_profile.id)
            )
            if normalize_company_name(company.name) == normalized_name
        ]

    if not matches:
        return clarification_result(
            "I do not see that company in your tracked companies yet. Do you want me to add it as a new company to follow, or did you mean a different tracked company?",
            "company_not_found",
            {"companyName": company_name},
        )
    if len(matches) > 1:
        return clarification_result(
            "I found multiple tracked companies with that name. Which one should I update?",
            "company_update_ambiguous_target",
            {"companyName": company_name, "matches": [serialize_company(company) for company in matches]},
        )
    return matched_company_result(matches[0])


def apply_url_update(company: TargetCompany, field: str, url: str) -> dict[str, Any]:
    if field == "source_urls":
        previous = company.source_urls or []
        seen = {item.casefold() for item in previous}
        if url.casefold() in seen:
            next_urls = previous
            changed = False
        else:
            next_urls = [*previous, url]
            changed = True
        company.source_urls = next_urls
        return {
            "updatedField": field,
            "previousValue": previous,
            "newValue": next_urls,
            "changed": changed,
            "appended": changed,
        }

    previous = getattr(company, field)
    setattr(company, field, url)
    return {
        "updatedField": field,
        "previousValue": previous,
        "newValue": url,
        "changed": previous != url,
    }


def normalize_http_url(value: str | None) -> str | None:
    stripped = clean_text(value)
    if stripped is None:
        return None
    stripped = stripped.rstrip(".,;:")
    parsed = urlparse(stripped)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return stripped


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def matched_company_result(company: TargetCompany) -> CompanyUpdateResult:
    return CompanyUpdateResult(
        status="completed",
        assistant_message="Company matched.",
        body={"ok": True, "companyRow": company},
    )


def clarification_result(message: str, code: str, details: dict[str, Any]) -> CompanyUpdateResult:
    return CompanyUpdateResult(
        status="needs_confirmation",
        assistant_message=message,
        body={"ok": False, "error": message, "code": code, **details},
    )


def failed_result(message: str, code: str, details: dict[str, Any]) -> CompanyUpdateResult:
    return CompanyUpdateResult(
        status="failed",
        assistant_message=message,
        body={"ok": False, "error": message, "code": code, **details},
    )
