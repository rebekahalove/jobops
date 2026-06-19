from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..company_sources.theirstack.models import TheirStackCompanySearchRequest
from ..db.models import (
    Application,
    CandidateCompany,
    CandidateProfile,
    CandidateSavedJob,
    Company,
    CompanySource,
    CompanySyncSignature,
    JobListing,
    ProfileFieldValue,
    RoleTarget,
)
from ..job_discovery.job_sync.service import normalize_sync_key_text
from .theirstack_service import upsert_theirstack_company_sync_signature


@dataclass(frozen=True)
class CompanySyncDerivationResult:
    signatures: tuple[CompanySyncSignature, ...]
    dry_run_signatures: tuple[dict[str, Any], ...] = ()
    diagnostics: dict[str, Any] | None = None


def derive_company_sync_signatures(
    session: Session,
    *,
    candidate_slug: str | None = None,
    all_active_profiles: bool = False,
    from_job_listings: bool = False,
    from_candidate_companies: bool = False,
    from_saved_jobs: bool = False,
    from_applications: bool = False,
    missing_company_metadata_only: bool = False,
    active_jobs_only: bool = False,
    recent_days: int = 30,
    min_active_jobs: int = 1,
    limit: int = 25,
    dry_run: bool = False,
    created_by: str | None = None,
    freshness_hours: int = 168,
    results_per_page: int = 25,
    max_pages: int = 1,
) -> CompanySyncDerivationResult:
    candidates = list_signature_candidates(
        session,
        candidate_slug=candidate_slug,
        all_active_profiles=all_active_profiles,
        from_job_listings=from_job_listings,
        from_candidate_companies=from_candidate_companies,
        from_saved_jobs=from_saved_jobs,
        from_applications=from_applications,
        missing_company_metadata_only=missing_company_metadata_only,
        active_jobs_only=active_jobs_only,
        recent_days=recent_days,
        min_active_jobs=min_active_jobs,
        limit=limit,
    )
    deduped = dedupe_signature_candidates(candidates)[: max(1, limit)]
    if dry_run:
        return CompanySyncDerivationResult(
            signatures=(),
            dry_run_signatures=tuple(deduped),
            diagnostics={"candidateCount": len(candidates), "dedupedCount": len(deduped), "dryRun": True},
        )

    signatures: list[CompanySyncSignature] = []
    for candidate in deduped:
        signature = upsert_theirstack_company_sync_signature(
            session,
            query_text=candidate["queryText"],
            request=candidate["request"],
            query_kind=candidate["queryKind"],
            source=candidate["source"],
            results_per_page=results_per_page,
            max_pages=max_pages,
            freshness_hours=freshness_hours,
            enabled=True,
            created_by=created_by,
            criteria_json=candidate["criteria"],
        )
        signatures.append(signature)
    return CompanySyncDerivationResult(
        signatures=tuple(signatures),
        diagnostics={"candidateCount": len(candidates), "dedupedCount": len(deduped), "createdOrUpdatedCount": len(signatures)},
    )


def list_signature_candidates(
    session: Session,
    *,
    candidate_slug: str | None,
    all_active_profiles: bool,
    from_job_listings: bool,
    from_candidate_companies: bool,
    from_saved_jobs: bool,
    from_applications: bool,
    missing_company_metadata_only: bool,
    active_jobs_only: bool,
    recent_days: int,
    min_active_jobs: int,
    limit: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    candidates.extend(profile_target_signature_candidates(session, candidate_slug=candidate_slug, all_active_profiles=all_active_profiles, limit=limit))
    if from_job_listings:
        candidates.extend(
            job_listing_signature_candidates(
                session,
                missing_company_metadata_only=missing_company_metadata_only,
                active_jobs_only=active_jobs_only,
                recent_days=recent_days,
                min_active_jobs=min_active_jobs,
                limit=limit,
            )
        )
    if from_candidate_companies:
        candidates.extend(
            known_company_signature_candidates(
                session,
                candidate_slug=candidate_slug,
                source_kind="candidate_company_enrichment",
                limit=limit,
            )
        )
    if from_saved_jobs:
        candidates.extend(saved_job_company_signature_candidates(session, candidate_slug=candidate_slug, limit=limit))
    if from_applications:
        candidates.extend(application_company_signature_candidates(session, candidate_slug=candidate_slug, limit=limit))
    return candidates


def profile_target_signature_candidates(
    session: Session,
    *,
    candidate_slug: str | None,
    all_active_profiles: bool,
    limit: int,
) -> list[dict[str, Any]]:
    statement = (
        select(RoleTarget, CandidateProfile)
        .join(CandidateProfile, RoleTarget.candidate_profile_id == CandidateProfile.id)
        .where(RoleTarget.is_active.is_(True))
        .order_by(RoleTarget.updated_at.desc())
        .limit(max(1, limit))
    )
    if candidate_slug:
        statement = statement.where(CandidateProfile.slug == candidate_slug)
    elif not all_active_profiles:
        return []
    profile_facts = profile_fact_terms_by_candidate(session)
    rows = list(session.execute(statement).all())
    if not rows:
        return []
    by_key: dict[str, dict[str, Any]] = {}
    for role_target, profile in rows:
        target_terms = clean_terms([*(role_target.target_titles or ()), *(role_target.role_families or ())])
        if not target_terms:
            continue
        skill_terms = profile_facts.get(profile.id, [])[:12]
        constraints = flatten_constraints(role_target.constraints or {})
        query_text = " / ".join(target_terms[:4])
        job_filters: dict[str, Any] = {
            "job_title_pattern_or": target_terms[:8],
            "posted_at_max_age_days": 30,
        }
        request = TheirStackCompanySearchRequest(
            job_filters=job_filters,
            company_description_pattern_or=tuple(clean_terms([*skill_terms, *constraints])[:8]),
        )
        key = f"profile:{normalize_sync_key_text(query_text)}:{normalize_sync_key_text(','.join(role_target.preferred_locations or []))}"
        existing = by_key.get(key)
        profile_id = profile.id
        metadata = {
            "source": "profile_target_context",
            "activeProfileCount": 1,
            "contributingCandidateProfileIds": [profile_id],
            "contributingRoleTargetIds": [role_target.id],
            "sourceFields": ["target_titles", "role_families", "skills", "constraints", "preferred_locations", "work_modes"],
            "targetTitles": list(role_target.target_titles or []),
            "roleFamilies": list(role_target.role_families or []),
            "seniority": role_target.seniority,
            "preferredLocations": list(role_target.preferred_locations or []),
            "workModes": list(role_target.work_modes or []),
            "constraints": role_target.constraints or {},
            "profileHeadlineIncluded": bool(profile.headline),
            "lastDerivedAt": datetime.now(UTC).isoformat(),
        }
        if existing:
            existing["criteria"]["demand"]["activeProfileCount"] += 1
            append_capped(existing["criteria"]["demand"]["contributingCandidateProfileIds"], profile_id)
            append_capped(existing["criteria"]["demand"]["contributingRoleTargetIds"], role_target.id)
            continue
        by_key[key] = {
            "queryText": query_text,
            "queryKind": "aggregate_target_role_company_discovery" if all_active_profiles and not candidate_slug else "target_role_company_discovery",
            "source": "profile_target_context",
            "request": request,
            "criteria": {"demand": metadata},
        }
    return list(by_key.values())


def job_listing_signature_candidates(
    session: Session,
    *,
    missing_company_metadata_only: bool,
    active_jobs_only: bool,
    recent_days: int,
    min_active_jobs: int,
    limit: int,
) -> list[dict[str, Any]]:
    cutoff = datetime.now(UTC) - timedelta(days=max(1, recent_days))
    statement = (
        select(Company, func.count(JobListing.id).label("job_count"))
        .join(JobListing, JobListing.company_id == Company.id)
        .options(selectinload(Company.sources))
        .group_by(Company.id)
        .order_by(func.count(JobListing.id).desc(), Company.updated_at.desc())
        .limit(max(1, limit * 3))
    )
    if active_jobs_only:
        statement = statement.where(JobListing.is_active.is_(True))
    candidates: list[dict[str, Any]] = []
    for company, job_count in session.execute(statement).all():
        if int(job_count or 0) < min_active_jobs:
            continue
        missing = missing_company_metadata_fields(company)
        if missing_company_metadata_only and not missing:
            continue
        recent_count = session.scalar(
            select(func.count(JobListing.id)).where(
                JobListing.company_id == company.id,
                JobListing.created_at >= cutoff,
            )
        )
        request = company_identity_request(company)
        if request is None:
            continue
        candidates.append(
            {
                "queryText": company.name,
                "queryKind": "job_listing_company_enrichment",
                "source": "job_listings",
                "request": request,
                "criteria": {
                    "derivation": {
                        "source": "job_listings",
                        "companyId": company.id,
                        "companyName": company.name,
                        "normalizedDomain": company.normalized_domain,
                        "activeJobCount": int(job_count or 0),
                        "recentJobCount": int(recent_count or 0),
                        "missingMetadataFields": missing,
                        "reason": "canonical job inventory company needs provider enrichment",
                        "lastDerivedAt": datetime.now(UTC).isoformat(),
                    }
                },
            }
        )
        if len(candidates) >= limit:
            break
    return candidates


def known_company_signature_candidates(
    session: Session,
    *,
    candidate_slug: str | None,
    source_kind: str,
    limit: int,
) -> list[dict[str, Any]]:
    statement = select(CandidateCompany).join(Company).options(selectinload(CandidateCompany.company)).order_by(CandidateCompany.added_at.desc()).limit(max(1, limit * 2))
    if candidate_slug:
        statement = statement.join(CandidateProfile, CandidateCompany.candidate_profile_id == CandidateProfile.id).where(CandidateProfile.slug == candidate_slug)
    candidates: list[dict[str, Any]] = []
    for link in session.scalars(statement).all():
        company = link.company
        missing = missing_company_metadata_fields(company)
        if not missing:
            continue
        request = company_identity_request(company)
        if request is None:
            continue
        candidates.append(company_enrichment_candidate(company, request, source_kind=source_kind, missing=missing, source="candidate_companies"))
        if len(candidates) >= limit:
            break
    return candidates


def saved_job_company_signature_candidates(session: Session, *, candidate_slug: str | None, limit: int) -> list[dict[str, Any]]:
    statement = select(CandidateSavedJob).options(selectinload(CandidateSavedJob.job_listing).selectinload(JobListing.company)).order_by(CandidateSavedJob.added_at.desc()).limit(max(1, limit * 2))
    if candidate_slug:
        statement = statement.join(CandidateProfile, CandidateSavedJob.candidate_profile_id == CandidateProfile.id).where(CandidateProfile.slug == candidate_slug)
    return company_candidates_from_objects(
        [saved.job_listing.company for saved in session.scalars(statement).all() if saved.job_listing and saved.job_listing.company],
        query_kind="saved_job_company_enrichment",
        source="saved_jobs",
        limit=limit,
    )


def application_company_signature_candidates(session: Session, *, candidate_slug: str | None, limit: int) -> list[dict[str, Any]]:
    statement = select(Application).options(selectinload(Application.company)).order_by(Application.created_at.desc()).limit(max(1, limit * 2))
    if candidate_slug:
        statement = statement.join(CandidateProfile, Application.candidate_profile_id == CandidateProfile.id).where(CandidateProfile.slug == candidate_slug)
    companies = []
    for application in session.scalars(statement).all():
        if application.company:
            companies.append(application.company)
        elif application.company_name:
            companies.append(Company(name=application.company_name, normalized_name=normalize_sync_key_text(application.company_name)))
    return company_candidates_from_objects(companies, query_kind="application_company_enrichment", source="applications", limit=limit)


def company_candidates_from_objects(companies: list[Company], *, query_kind: str, source: str, limit: int) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for company in companies:
        key = company.normalized_domain or company.normalized_name or normalize_sync_key_text(company.name)
        if not key or key in seen:
            continue
        seen.add(key)
        missing = missing_company_metadata_fields(company)
        if not missing:
            continue
        request = company_identity_request(company)
        if request is None:
            continue
        candidates.append(company_enrichment_candidate(company, request, source_kind=query_kind, missing=missing, source=source))
        if len(candidates) >= limit:
            break
    return candidates


def company_enrichment_candidate(
    company: Company,
    request: TheirStackCompanySearchRequest,
    *,
    source_kind: str,
    missing: list[str],
    source: str,
) -> dict[str, Any]:
    return {
        "queryText": company.name,
        "queryKind": source_kind,
        "source": source,
        "request": request,
        "criteria": {
            "derivation": {
                "source": source,
                "companyId": getattr(company, "id", None),
                "companyName": company.name,
                "normalizedDomain": company.normalized_domain,
                "missingMetadataFields": missing,
                "reason": "known user-linked company needs provider enrichment",
                "lastDerivedAt": datetime.now(UTC).isoformat(),
            }
        },
    }


def dedupe_signature_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        request = candidate["request"]
        body = request.to_api_body(page=1)
        key = normalize_sync_key_text(f"{candidate['queryKind']}:{body}")
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = candidate
            continue
        merge_demand_metadata(existing["criteria"], candidate["criteria"])
    return list(deduped.values())


def merge_demand_metadata(target: dict[str, Any], source: dict[str, Any]) -> None:
    target_demand = target.setdefault("demand", {})
    source_demand = source.get("demand") or {}
    if not source_demand:
        return
    target_demand["activeProfileCount"] = int(target_demand.get("activeProfileCount") or 0) + int(source_demand.get("activeProfileCount") or 0)
    for key in ("contributingCandidateProfileIds", "contributingRoleTargetIds", "sourceFields"):
        values = target_demand.setdefault(key, [])
        for value in source_demand.get(key) or []:
            append_capped(values, value)


def profile_fact_terms_by_candidate(session: Session) -> dict[str, list[str]]:
    rows = session.execute(
        select(ProfileFieldValue.candidate_profile_id, ProfileFieldValue.value_text)
        .where(ProfileFieldValue.lifecycle_status != "archived")
        .order_by(ProfileFieldValue.updated_at.desc())
    ).all()
    terms_by_profile: dict[str, list[str]] = {}
    for candidate_profile_id, value_text in rows:
        if not value_text:
            continue
        terms_by_profile.setdefault(candidate_profile_id, [])
        terms_by_profile[candidate_profile_id].extend(clean_terms(value_text.split(","))[:8])
    return {key: values[:20] for key, values in terms_by_profile.items()}


def missing_company_metadata_fields(company: Company) -> list[str]:
    missing: list[str] = []
    for field_name in ("domain", "website_url", "careers_url", "job_listings_url"):
        if not getattr(company, field_name, None):
            missing.append(field_name)
    if not company.greenhouse_board_token and not company.ashby_board_url and not company.lever_slug:
        missing.append("ats_metadata")
    latest_source = latest_company_source_synced_at(company)
    if latest_source is None:
        missing.append("company_source")
    elif latest_source < datetime.now(UTC) - timedelta(days=30):
        missing.append("stale_company_source")
    return missing


def latest_company_source_synced_at(company: Company) -> datetime | None:
    latest: datetime | None = None
    for source in getattr(company, "sources", []) or []:
        value = source.last_synced_at or source.last_seen_at
        if value is None:
            continue
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        latest = value if latest is None or value > latest else latest
    return latest


def company_identity_request(company: Company) -> TheirStackCompanySearchRequest | None:
    if company.normalized_domain or company.domain:
        return TheirStackCompanySearchRequest(company_domain_or=(company.normalized_domain or company.domain or "",))
    if company.name:
        return TheirStackCompanySearchRequest(company_name_or=(company.name,), company_name_partial_match_or=(company.name,))
    return None


def clean_terms(values: list[str] | tuple[str, ...]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = " ".join(str(value).split()).strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return cleaned


def flatten_constraints(constraints: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    for value in constraints.values():
        if isinstance(value, str):
            terms.append(value)
        elif isinstance(value, list):
            terms.extend(str(item) for item in value)
    return clean_terms(terms)


def append_capped(values: list[Any], value: Any, *, cap: int = 20) -> None:
    if value in values or len(values) >= cap:
        return
    values.append(value)
