from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .company_canonicalization import normalize_company_name
from .company_discovery import serialize_company
from .db.models import CandidateCompany, CandidateProfile, Company


CompanyUpdateField = Literal["website_url", "careers_url", "job_listings_url", "source_urls", "notes", "review_status", "fit_reason"]
CompanyUpdateStatus = Literal["completed", "needs_confirmation", "failed"]

ALLOWED_COMPANY_UPDATE_FIELDS: set[str] = {
    "website_url",
    "careers_url",
    "job_listings_url",
    "source_urls",
    "notes",
    "review_status",
    "fit_reason",
}
URL_COMPANY_UPDATE_FIELDS: set[str] = {"website_url", "careers_url", "job_listings_url", "source_urls"}
LINK_COMPANY_UPDATE_FIELDS: set[str] = {"notes", "review_status", "fit_reason"}


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

    link = company_match.body["companyLink"]
    assert isinstance(link, CandidateCompany)

    if field in URL_COMPANY_UPDATE_FIELDS:
        url = normalize_http_url(request.url)
        if url is None:
            return failed_result(
                "A valid http(s) URL is required for that company update.",
                "company_update_url_required",
                {"field": field},
            )
        result = apply_url_update(link.company, field, url)
    else:
        note_text = clean_text(request.raw_text)
        if note_text is None:
            return failed_result(
                "A note value is required for that company update.",
                "company_update_value_required",
                {"field": field},
            )
        previous = getattr(link, field) or ""
        setattr(link, field, note_text)
        result = {
            "updatedField": field,
            "previousValue": previous,
            "newValue": getattr(link, field),
            "changed": previous != getattr(link, field),
        }

    db_session.add(link.company)
    db_session.add(link)
    db_session.commit()
    db_session.refresh(link)

    field_label = field.replace("_", " ")
    return CompanyUpdateResult(
        status="completed",
        assistant_message=f"Updated {link.company.name}'s {field_label}.",
        body={
            "ok": True,
            "result": {
                "assistantMessage": f"Updated {link.company.name}'s {field_label}.",
                "company": serialize_company(link),
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
        link = session.get(CandidateCompany, company_id)
        if link is not None and link.candidate_profile_id == candidate_profile.id:
            return matched_company_result(link)

        company = session.get(Company, company_id)
        if company is not None:
            link = session.scalar(
                select(CandidateCompany)
                .options(selectinload(CandidateCompany.company))
                .where(
                    CandidateCompany.candidate_profile_id == candidate_profile.id,
                    CandidateCompany.company_id == company.id,
                )
            )
            if link is not None:
                return matched_company_result(link)

        return clarification_result(
            "I do not see that company in your tracked companies yet. Do you want me to add it as a new company to follow, or did you mean a different tracked company?",
            "company_not_found",
            {"companyId": company_id},
        )

    normalized_name = normalize_company_name(company_name)
    if not normalized_name:
        return clarification_result(
            "Which tracked company should I update?",
            "company_update_target_required",
            {},
        )

    all_links = list(
        session.scalars(
            select(CandidateCompany)
            .options(selectinload(CandidateCompany.company))
            .where(CandidateCompany.candidate_profile_id == candidate_profile.id)
        )
    )
    matches = [
        link
        for link in all_links
        if link.company is not None
        and normalize_company_name(link.company.normalized_name or link.company.name) == normalized_name
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
            {"companyName": company_name, "matches": [serialize_company(link) for link in matches]},
        )
    return matched_company_result(matches[0])


def apply_url_update(company: Company, field: str, url: str) -> dict[str, Any]:
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
    if field in {"website_url", "careers_url", "job_listings_url"} and not company.normalized_domain:
        parsed_domain = domain_from_update_url(url)
        if parsed_domain:
            company.domain = company.domain or parsed_domain
            company.normalized_domain = parsed_domain
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


def domain_from_update_url(value: str) -> str | None:
    parsed = urlparse(value)
    return (parsed.hostname or "").casefold().removeprefix("www.") or None


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def matched_company_result(link: CandidateCompany) -> CompanyUpdateResult:
    return CompanyUpdateResult(
        status="completed",
        assistant_message="Company matched.",
        body={"ok": True, "companyLink": link},
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
