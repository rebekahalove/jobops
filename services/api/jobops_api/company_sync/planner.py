from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..company_enrichment import parse_json_object, parse_theirstack_search_request, term_is_grounded
from ..company_sources.theirstack.models import TheirStackCompanySearchRequest
from ..db.models import Application, CandidateCompany, CandidateProfile, CandidateSavedJob, JobListing, ProfileFieldValue, RoleTarget
from ..model_connector import ModelConnector, ModelMessage, ModelRequest


SEMANTIC_QUERY_KINDS = {"target_role_company_discovery", "aggregate_target_role_company_discovery", "profile_context_company_discovery"}
MAX_PLANNED_SIGNATURES = 10
SUPPORTED_JOB_FILTER_KEYS = {"job_title_pattern_or", "job_title_pattern_and", "job_country_code_or", "posted_at_max_age_days"}
ALLOWED_GROUNDING_TYPES = {
    "exact",
    "semantic_variant",
    "broader_role_family",
    "narrower_specialization",
    "technology_supported",
    "domain_supported",
    "location_supported",
    "company_identity",
}
RISKY_CATEGORY_TERMS = {
    "defense",
    "military",
    "weapon",
    "weapons",
    "surveillance",
    "policing",
    "law enforcement",
    "nursing",
    "clinical",
    "healthcare",
}


@dataclass(frozen=True)
class PlannedCompanySyncSignature:
    query_text: str
    query_kind: str
    request: TheirStackCompanySearchRequest
    criteria_json: dict[str, Any]
    verification_status: str
    enabled: bool
    validation_issues: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class CompanySyncSignaturePlanningResult:
    signatures: tuple[PlannedCompanySyncSignature, ...]
    rejected_ideas: tuple[dict[str, Any], ...]
    assistant_message: str | None
    diagnostics: dict[str, Any]


class CompanySyncSignaturePlanModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    query_text: str = Field(validation_alias=AliasChoices("query_text", "queryText"), max_length=240)
    query_kind: str = Field(default="target_role_company_discovery", validation_alias=AliasChoices("query_kind", "queryKind"), max_length=80)
    rationale: str | None = Field(default=None, max_length=900)
    source_fields_used: list[str] = Field(default_factory=list, validation_alias=AliasChoices("source_fields_used", "sourceFieldsUsed"), max_length=24)
    grounding: list[dict[str, Any]] = Field(default_factory=list, max_length=40)
    theirstack_request: dict[str, Any] = Field(default_factory=dict, validation_alias=AliasChoices("theirstack_request", "theirstackRequest"))
    confidence: str = Field(default="medium", max_length=40)
    needs_review: bool = Field(default=False, validation_alias=AliasChoices("needs_review", "needsReview"))


class RejectedCompanySyncIdeaModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    query_text: str | None = Field(default=None, validation_alias=AliasChoices("query_text", "queryText"), max_length=240)
    reason: str | None = Field(default=None, max_length=900)


class CompanySyncSignaturePlannerOutputModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    assistant_message: str | None = Field(default=None, validation_alias=AliasChoices("assistant_message", "assistantMessage"), max_length=900)
    signatures: list[CompanySyncSignaturePlanModel] = Field(default_factory=list, max_length=MAX_PLANNED_SIGNATURES)
    rejected_ideas: list[RejectedCompanySyncIdeaModel] = Field(default_factory=list, validation_alias=AliasChoices("rejected_ideas", "rejectedIdeas"), max_length=20)


def plan_company_sync_signatures(
    session: Session,
    *,
    connector: ModelConnector,
    candidate_slug: str | None = None,
    all_active_profiles: bool = False,
    latest_user_request: str | None = None,
    limit: int = 25,
    results_per_page: int = 25,
    max_pages: int = 1,
) -> CompanySyncSignaturePlanningResult:
    context = build_company_sync_signature_planner_context(
        session,
        candidate_slug=candidate_slug,
        all_active_profiles=all_active_profiles,
        latest_user_request=latest_user_request,
        limit=limit,
    )
    request = build_company_sync_signature_planner_request(context)
    response = connector.generate(request)
    output = parse_company_sync_signature_planner_output(response.text)
    context_text = json.dumps(context, sort_keys=True)
    reference_catalog = grounding_reference_catalog(context)
    planned: list[PlannedCompanySyncSignature] = []
    rejected_ideas = [idea.model_dump(by_alias=True) for idea in output.rejected_ideas]
    for model in output.signatures:
        validated = validate_planned_company_sync_signature(
            model,
            context_text=context_text,
            reference_catalog=reference_catalog,
            latest_user_request=latest_user_request,
            results_per_page=results_per_page,
            max_pages=max_pages,
            assistant_message=output.assistant_message,
            rejected_ideas=rejected_ideas,
        )
        if validated is not None:
            planned.append(validated)
    return CompanySyncSignaturePlanningResult(
        signatures=tuple(planned),
        rejected_ideas=tuple(rejected_ideas),
        assistant_message=output.assistant_message,
        diagnostics={
            "modelProvider": response.provider,
            "modelName": response.model,
            "plannedSignatureCount": len(output.signatures),
            "acceptedSignatureCount": len(planned),
            "rejectedIdeaCount": len(rejected_ideas),
        },
    )


def parse_company_sync_signature_planner_output(raw_text: str) -> CompanySyncSignaturePlannerOutputModel:
    try:
        parsed = parse_json_object(raw_text)
        return CompanySyncSignaturePlannerOutputModel.model_validate(parsed)
    except (ValueError, ValidationError) as error:
        raise ValueError("Company sync signature planner returned invalid JSON.") from error


def validate_planned_company_sync_signature(
    model: CompanySyncSignaturePlanModel,
    *,
    context_text: str,
    reference_catalog: set[tuple[str, str]],
    latest_user_request: str | None,
    results_per_page: int,
    max_pages: int,
    assistant_message: str | None,
    rejected_ideas: list[dict[str, Any]],
) -> PlannedCompanySyncSignature | None:
    query_text = " ".join(model.query_text.split()).strip()
    if not query_text:
        return None
    query_kind = model.query_kind if model.query_kind in SEMANTIC_QUERY_KINDS else "target_role_company_discovery"
    request = parse_theirstack_search_request(model.theirstack_request)
    grounding_by_term = build_grounding_by_term(model.grounding)
    request, validation_issues = clamp_and_validate_request(
        request,
        context_text=context_text,
        reference_catalog=reference_catalog,
        grounding_by_term=grounding_by_term,
        latest_user_request=latest_user_request,
        results_per_page=results_per_page,
        max_pages=max_pages,
    )
    if not request_has_meaningful_criteria(request):
        validation_issues.append({"code": "empty_or_ungrounded_search", "message": "No grounded bounded TheirStack criteria remained after validation."})
        if not model.needs_review and not broad_discovery_explicitly_requested(latest_user_request):
            return None
    verification_status = "needs_review" if model.needs_review or backend_requires_needs_review(validation_issues, request) else "verified"
    criteria_json = {
        "modelPlanning": {
            "assistantMessage": assistant_message,
            "rationale": model.rationale,
            "sourceFieldsUsed": compact_strings(model.source_fields_used, limit=24),
            "grounding": compact_grounding(model.grounding),
            "confidence": model.confidence,
            "needsReview": model.needs_review,
            "validationIssues": validation_issues,
            "rejectedIdeas": rejected_ideas,
        },
        "demand": {
            "source": "model_planned_profile_target_context",
            "sourceFields": compact_strings(model.source_fields_used, limit=24),
        },
    }
    return PlannedCompanySyncSignature(
        query_text=query_text,
        query_kind=query_kind,
        request=request,
        criteria_json=criteria_json,
        verification_status=verification_status,
        enabled=verification_status != "needs_review",
        validation_issues=tuple(validation_issues),
    )


def clamp_and_validate_request(
    request: TheirStackCompanySearchRequest,
    *,
    context_text: str,
    reference_catalog: set[tuple[str, str]],
    grounding_by_term: dict[str, dict[str, Any]],
    latest_user_request: str | None,
    results_per_page: int,
    max_pages: int,
) -> tuple[TheirStackCompanySearchRequest, list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    limit = request.limit or results_per_page
    bounded_limit = max(1, min(limit, max(1, results_per_page)))
    if limit != bounded_limit:
        issues.append({"code": "limit_clamped", "from": limit, "to": bounded_limit})
    planned_pages = request.max_pages or max_pages
    bounded_pages = max(1, min(planned_pages, max(1, max_pages)))
    if planned_pages != bounded_pages:
        issues.append({"code": "max_pages_clamped", "from": planned_pages, "to": bounded_pages})
    job_filters: dict[str, Any] = {}
    for key, value in (request.job_filters or {}).items():
        if key not in SUPPORTED_JOB_FILTER_KEYS:
            issues.append({"code": "unsupported_filter_removed", "field": f"job_filters.{key}"})
            continue
        if key == "posted_at_max_age_days":
            try:
                job_filters[key] = max(1, min(int(value), 365))
            except (TypeError, ValueError):
                issues.append({"code": "unsupported_filter_removed", "field": key})
            continue
        if isinstance(value, list):
            kept = [
                item
                for item in value
                if isinstance(item, str)
                and term_is_supported_by_context_or_grounding(
                    item,
                    context_text=context_text,
                    reference_catalog=reference_catalog,
                    grounding_by_term=grounding_by_term,
                    issues=issues,
                    field_name=key,
                )
            ]
            removed = [item for item in value if isinstance(item, str) and item not in kept]
            if removed:
                issues.append({"code": "ungrounded_filter_removed", "field": key, "values": removed})
            if kept:
                job_filters[key] = compact_strings(kept, limit=24)
        elif isinstance(value, str) and term_is_supported_by_context_or_grounding(
            value,
            context_text=context_text,
            reference_catalog=reference_catalog,
            grounding_by_term=grounding_by_term,
            issues=issues,
            field_name=key,
        ):
            job_filters[key] = value
        elif value:
            issues.append({"code": "ungrounded_filter_removed", "field": key, "values": [str(value)]})

    return (
        TheirStackCompanySearchRequest(
            company_name_or=grounded_tuple(request.company_name_or, "company_name_or", context_text, reference_catalog, grounding_by_term, issues),
            company_name_partial_match_or=grounded_tuple(request.company_name_partial_match_or, "company_name_partial_match_or", context_text, reference_catalog, grounding_by_term, issues),
            company_domain_or=grounded_tuple(request.company_domain_or, "company_domain_or", context_text, reference_catalog, grounding_by_term, issues),
            company_country_code_or=grounded_tuple(request.company_country_code_or, "company_country_code_or", context_text, reference_catalog, grounding_by_term, issues),
            company_description_pattern_or=grounded_tuple(request.company_description_pattern_or, "company_description_pattern_or", context_text, reference_catalog, grounding_by_term, issues),
            company_technology_slug_or=grounded_tuple(request.company_technology_slug_or, "company_technology_slug_or", context_text, reference_catalog, grounding_by_term, issues),
            company_technology_slug_and=grounded_tuple(request.company_technology_slug_and, "company_technology_slug_and", context_text, reference_catalog, grounding_by_term, issues),
            company_keyword_slug_or=grounded_tuple(request.company_keyword_slug_or, "company_keyword_slug_or", context_text, reference_catalog, grounding_by_term, issues),
            job_filters=job_filters,
            limit=bounded_limit,
            page=1,
            max_pages=bounded_pages,
            include_total_results=True,
        ),
        issues,
    )


def grounded_tuple(
    values: tuple[str, ...],
    field_name: str,
    context_text: str,
    reference_catalog: set[tuple[str, str]],
    grounding_by_term: dict[str, dict[str, Any]],
    issues: list[dict[str, Any]],
) -> tuple[str, ...]:
    kept = tuple(
        value
        for value in values
        if term_is_supported_by_context_or_grounding(
            value,
            context_text=context_text,
            reference_catalog=reference_catalog,
            grounding_by_term=grounding_by_term,
            issues=issues,
            field_name=field_name,
        )
    )
    removed = [value for value in values if value not in kept]
    if removed:
        issues.append({"code": "ungrounded_filter_removed", "field": field_name, "values": removed})
    return tuple(compact_strings(list(kept), limit=24))


def term_is_supported_by_context_or_grounding(
    term: str,
    *,
    context_text: str,
    reference_catalog: set[tuple[str, str]],
    grounding_by_term: dict[str, dict[str, Any]],
    issues: list[dict[str, Any]],
    field_name: str,
) -> bool:
    if term_is_grounded(term, context_text):
        return True
    grounding = grounding_by_term.get(normalize_term_key(term))
    if grounding is None:
        if term_has_unsupported_risky_category(term, context_text):
            issues.append({"code": "unsupported_risky_category_removed", "field": field_name, "term": term, "needsReviewCandidate": True})
        return False
    valid, issue = validate_term_grounding(term, grounding, reference_catalog=reference_catalog, context_text=context_text)
    if not valid:
        issues.append({"code": "invalid_grounding_removed", "field": field_name, "term": term, **issue, "needsReviewCandidate": True})
        return False
    if term_has_unsupported_risky_category(term, context_text):
        issues.append({"code": "unsupported_risky_category_removed", "field": field_name, "term": term, "needsReviewCandidate": True})
        return False
    return True


def validate_term_grounding(
    term: str,
    grounding: dict[str, Any],
    *,
    reference_catalog: set[tuple[str, str]],
    context_text: str,
) -> tuple[bool, dict[str, Any]]:
    grounding_type = grounding.get("groundingType")
    if grounding_type not in ALLOWED_GROUNDING_TYPES:
        return False, {"groundingType": grounding_type or "missing"}
    rationale = grounding.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        return False, {"reason": "missing_rationale"}
    based_on = grounding.get("basedOn")
    if not isinstance(based_on, list) or not based_on:
        return False, {"reason": "missing_based_on"}
    invalid_refs: list[dict[str, Any]] = []
    valid_ref_count = 0
    for ref in based_on:
        if not isinstance(ref, dict):
            invalid_refs.append({"reason": "invalid_reference"})
            continue
        field = str(ref.get("field") or "").strip()
        value = str(ref.get("value") or "").strip()
        if not field or not value:
            invalid_refs.append({"field": field, "value": value, "reason": "empty_reference"})
            continue
        if reference_exists(field, value, reference_catalog=reference_catalog, context_text=context_text):
            valid_ref_count += 1
        else:
            invalid_refs.append({"field": field, "value": value, "reason": "not_in_context"})
    if valid_ref_count <= 0:
        return False, {"reason": "unverified_references", "invalidReferences": invalid_refs[:5]}
    return True, {}


def reference_exists(field: str, value: str, *, reference_catalog: set[tuple[str, str]], context_text: str) -> bool:
    normalized_field = field.casefold()
    normalized_value = normalize_term_key(value)
    if (normalized_field, normalized_value) in reference_catalog:
        return True
    if normalized_value and term_is_grounded(value, context_text):
        return True
    return False


def build_grounding_by_term(values: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_term: dict[str, dict[str, Any]] = {}
    for value in values:
        if not isinstance(value, dict):
            continue
        term = value.get("term")
        if isinstance(term, str) and term.strip():
            by_term[normalize_term_key(term)] = value
    return by_term


def backend_requires_needs_review(issues: list[dict[str, Any]], request: TheirStackCompanySearchRequest) -> bool:
    if not request_has_meaningful_criteria(request):
        return True
    return any(bool(issue.get("forceNeedsReview")) for issue in issues)


def term_has_unsupported_risky_category(term: str, context_text: str) -> bool:
    normalized_term = normalize_term_key(term)
    normalized_context = normalize_term_key(context_text)
    return any(risky in normalized_term and risky not in normalized_context for risky in RISKY_CATEGORY_TERMS)


def normalize_term_key(value: str) -> str:
    return " ".join(str(value or "").casefold().replace("_", " ").replace("-", " ").split())


def request_has_meaningful_criteria(request: TheirStackCompanySearchRequest) -> bool:
    semantic_job_filters = {
        key: value
        for key, value in (request.job_filters or {}).items()
        if key != "posted_at_max_age_days" and value
    }
    return bool(
        request.company_name_or
        or request.company_name_partial_match_or
        or request.company_domain_or
        or request.company_country_code_or
        or request.company_description_pattern_or
        or request.company_technology_slug_or
        or request.company_technology_slug_and
        or request.company_keyword_slug_or
        or semantic_job_filters
    )


def broad_discovery_explicitly_requested(latest_user_request: str | None) -> bool:
    text = (latest_user_request or "").casefold()
    return any(phrase in text for phrase in ("broad", "exploratory", "open ended", "open-ended", "general company discovery"))


def build_company_sync_signature_planner_context(
    session: Session,
    *,
    candidate_slug: str | None,
    all_active_profiles: bool,
    latest_user_request: str | None,
    limit: int,
) -> dict[str, Any]:
    profiles = load_candidate_profiles_for_planning(session, candidate_slug=candidate_slug, all_active_profiles=all_active_profiles, limit=limit)
    profile_ids = [profile.id for profile in profiles]
    profile_contexts = [profile_context_for_planning(session, profile) for profile in profiles]
    profile_fact_context = profile_fact_context_by_candidate(session, profile_ids)
    return {
        "latest_user_request": latest_user_request,
        "profiles": profile_contexts,
        "profile_fact_context": profile_fact_context,
        "current_saved_companies": saved_company_context_by_candidate(session, profile_ids),
        "saved_jobs": saved_job_context_by_candidate(session, profile_ids),
        "applications": application_context_by_candidate(session, profile_ids),
        "grounding_reference_catalog": build_grounding_reference_catalog(profile_contexts, profile_fact_context),
        "planner_rules": {
            "provider": "theirstack",
            "bounded": True,
            "no_provider_api_call_during_planning": True,
            "allowed_job_filter_keys": sorted(SUPPORTED_JOB_FILTER_KEYS),
        },
    }


def grounding_reference_catalog(context: dict[str, Any]) -> set[tuple[str, str]]:
    values: set[tuple[str, str]] = set()
    raw_catalog = context.get("grounding_reference_catalog")
    if isinstance(raw_catalog, list):
        for item in raw_catalog:
            if not isinstance(item, dict):
                continue
            field = str(item.get("field") or "").strip().casefold()
            value = normalize_term_key(str(item.get("value") or ""))
            if field and value:
                values.add((field, value))
    return values


def build_grounding_reference_catalog(
    profile_contexts: list[dict[str, Any]],
    profile_fact_context: dict[str, list[dict[str, Any]]],
) -> list[dict[str, str]]:
    references: list[dict[str, str]] = []
    for profile in profile_contexts:
        add_reference(references, "CandidateProfile.headline", profile.get("headline"))
        for target in profile.get("roleTargets") or []:
            if not isinstance(target, dict):
                continue
            for value in target.get("targetTitles") or []:
                add_reference(references, "RoleTarget.target_titles", value)
            for value in target.get("roleFamilies") or []:
                add_reference(references, "RoleTarget.role_families", value)
            add_reference(references, "RoleTarget.seniority", target.get("seniority"))
            for value in target.get("preferredLocations") or []:
                add_reference(references, "RoleTarget.preferred_locations", value)
            for value in target.get("workModes") or []:
                add_reference(references, "RoleTarget.work_modes", value)
            constraints = target.get("constraints")
            if isinstance(constraints, dict):
                for value in flatten_reference_values(constraints):
                    add_reference(references, "RoleTarget.constraints", value)
    for facts in profile_fact_context.values():
        for fact in facts:
            field_name = str(fact.get("fieldName") or "value")
            value = fact.get("valueText")
            add_reference(references, f"ProfileFieldValue.{field_name}", value)
            add_reference(references, "ProfileFieldValue.skills", value)
    return references


def add_reference(references: list[dict[str, str]], field: str, value: Any) -> None:
    if not isinstance(value, str):
        return
    cleaned = " ".join(value.split()).strip()
    if cleaned:
        references.append({"field": field, "value": cleaned})


def flatten_reference_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    if isinstance(value, dict):
        values: list[str] = []
        for item in value.values():
            values.extend(flatten_reference_values(item))
        return values
    return []


def load_candidate_profiles_for_planning(
    session: Session,
    *,
    candidate_slug: str | None,
    all_active_profiles: bool,
    limit: int,
) -> list[CandidateProfile]:
    statement = select(CandidateProfile).order_by(CandidateProfile.updated_at.desc()).limit(max(1, limit))
    if candidate_slug:
        statement = statement.where(CandidateProfile.slug == candidate_slug)
    elif not all_active_profiles:
        return []
    return list(session.scalars(statement).all())


def profile_context_for_planning(session: Session, profile: CandidateProfile) -> dict[str, Any]:
    role_targets = list(
        session.scalars(
            select(RoleTarget)
            .where(RoleTarget.candidate_profile_id == profile.id, RoleTarget.is_active.is_(True))
            .order_by(RoleTarget.updated_at.desc())
        ).all()
    )
    return {
        "candidateProfileId": profile.id,
        "slug": profile.slug,
        "headline": profile.headline,
        "roleTargets": [
            {
                "roleTargetId": target.id,
                "targetTitles": target.target_titles or [],
                "roleFamilies": target.role_families or [],
                "seniority": target.seniority,
                "preferredLocations": target.preferred_locations or [],
                "workModes": target.work_modes or [],
                "constraints": target.constraints or {},
            }
            for target in role_targets
        ],
    }


def profile_fact_context_by_candidate(session: Session, profile_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not profile_ids:
        return {}
    rows = session.scalars(
        select(ProfileFieldValue)
        .where(ProfileFieldValue.candidate_profile_id.in_(profile_ids), ProfileFieldValue.lifecycle_status != "archived")
        .order_by(ProfileFieldValue.updated_at.desc())
        .limit(80)
    ).all()
    values: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        values.setdefault(row.candidate_profile_id, []).append(
            {
                "fieldGroup": row.field_group,
                "fieldName": row.field_name,
                "valueText": row.value_text,
            }
        )
    return values


def saved_company_context_by_candidate(session: Session, profile_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not profile_ids:
        return {}
    rows = session.scalars(
        select(CandidateCompany).where(CandidateCompany.candidate_profile_id.in_(profile_ids)).limit(50)
    ).all()
    values: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        values.setdefault(row.candidate_profile_id, []).append({"companyId": row.company_id, "discoveredBy": row.discovered_by})
    return values


def saved_job_context_by_candidate(session: Session, profile_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not profile_ids:
        return {}
    rows = session.scalars(
        select(CandidateSavedJob).where(CandidateSavedJob.candidate_profile_id.in_(profile_ids)).limit(50)
    ).all()
    values: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        listing = row.job_listing
        values.setdefault(row.candidate_profile_id, []).append(
            {
                "status": row.status,
                "companyName": listing.company_name if listing else None,
                "title": listing.title if listing else None,
            }
        )
    return values


def application_context_by_candidate(session: Session, profile_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not profile_ids:
        return {}
    rows = session.scalars(select(Application).where(Application.candidate_profile_id.in_(profile_ids)).limit(50)).all()
    values: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        values.setdefault(row.candidate_profile_id, []).append(
            {
                "companyName": row.company_name,
                "jobTitle": row.job_title,
                "status": row.status,
            }
        )
    return values


def build_company_sync_signature_planner_request(context: dict[str, Any]) -> ModelRequest:
    return ModelRequest(
        task="company_sync_signature_planner",
        temperature=0,
        max_output_tokens=6000,
        response_mime_type="application/json",
        search_grounding=False,
        metadata={"feature": "company_sync_signature_planner"},
        messages=[
            ModelMessage(role="system", content=COMPANY_SYNC_SIGNATURE_PLANNER_PROMPT),
            ModelMessage(role="user", content=json.dumps(context, indent=2)),
        ],
    )


def compact_strings(values: list[Any], *, limit: int) -> list[str]:
    compacted: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        cleaned = " ".join(value.split()).strip()[:160]
        key = cleaned.casefold()
        if cleaned and key not in seen:
            compacted.append(cleaned)
            seen.add(key)
        if len(compacted) >= limit:
            break
    return compacted


def compact_grounding(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    for value in values[:40]:
        if not isinstance(value, dict):
            continue
        term = value.get("term")
        if isinstance(term, str) and term.strip():
            compacted.append(
                {
                    "term": term[:160],
                    "groundingType": str(value.get("groundingType") or "")[:80],
                    "basedOn": compact_grounding_refs(value.get("basedOn")),
                    "rationale": str(value.get("rationale") or "")[:900],
                }
            )
            continue
        field = value.get("field")
        grounded_value = value.get("value")
        if isinstance(field, str) and isinstance(grounded_value, str):
            compacted.append({"field": field[:160], "value": grounded_value[:240]})
    return compacted


def compact_grounding_refs(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    refs: list[dict[str, str]] = []
    for item in value[:12]:
        if not isinstance(item, dict):
            continue
        field = item.get("field")
        grounded_value = item.get("value")
        if isinstance(field, str) and isinstance(grounded_value, str):
            refs.append({"field": field[:160], "value": grounded_value[:240]})
    return refs


COMPANY_SYNC_SIGNATURE_PLANNER_PROMPT = """You are the JobOps Company Sync Signature Planner.

Return JSON only. Propose bounded TheirStack company-search sync signatures from the supplied authenticated profile,
target, saved-company, saved-job, application, and latest-user-request context.

Rules:
- The backend will validate, clamp, dedupe, and persist signatures. Do not call providers.
- Propose semantic company discovery signatures only when grounded in supplied context.
- Do not invent roles, industries, domains, technologies, geographies, company names, or job filters.
- For each search term or job filter term that is not an exact literal context value, include grounding metadata with:
  term, groundingType, basedOn references, and rationale.
- Valid groundingType values: exact, semantic_variant, broader_role_family, narrower_specialization,
  technology_supported, domain_supported, location_supported, company_identity, unsupported.
- Use unsupported when a term seems useful but should be human-reviewed before automatic sync.
- Use TheirStack jobFilters for hiring-signal discovery when grounded target roles are present.
- Keep searches bounded: limit <= 25 and maxPages <= 1 unless explicitly asked otherwise in context.
- Set needsReview=true if useful but not fully grounded.
- Empty or generic broad searches are allowed only when the latest request explicitly asks for broad company discovery.
- TheirStack is a company/hiring-signal source, not the canonical job-detail provider.

Return this JSON shape:
{
  "assistantMessage": "Short admin-only diagnostic summary.",
  "signatures": [
    {
      "queryText": "Applied AI platform engineering companies",
      "queryKind": "target_role_company_discovery",
      "rationale": "Derived from target titles and role family.",
      "sourceFieldsUsed": ["target_titles", "role_families"],
      "grounding": [
        {
          "term": "LLM Engineer",
          "groundingType": "semantic_variant",
          "basedOn": [{"field": "RoleTarget.target_titles", "value": "Applied AI Engineer"}],
          "rationale": "LLM Engineer is a hiring-market specialization of applied AI work."
        }
      ],
      "theirstackRequest": {
        "companyNameOr": [],
        "companyNamePartialMatchOr": [],
        "companyDomainOr": [],
        "companyCountryCodeOr": [],
        "companyDescriptionPatternOr": [],
        "companyTechnologySlugOr": [],
        "companyTechnologySlugAnd": [],
        "companyKeywordSlugOr": [],
        "jobFilters": {"job_title_pattern_or": ["Applied AI Engineer"], "posted_at_max_age_days": 30},
        "limit": 25,
        "maxPages": 1
      },
      "confidence": "medium",
      "needsReview": false
    }
  ],
  "rejectedIdeas": [{"queryText": "Example rejected query", "reason": "Not grounded in supplied context."}]
}"""
