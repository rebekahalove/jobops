from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from jobops_api.db.models import (
    CandidateProfile,
    Domain,
    EvidenceArtifact,
    ExperienceProjectDraft,
    ProfileFact,
    ProfileFactDraft,
    RoleTarget,
    SkillClaim,
    Tenant,
)


def candidate_profile_to_public_dict(candidate_profile: CandidateProfile) -> dict[str, Any]:
    session = object_session(candidate_profile)
    fact_rows = (
        list(
            session.scalars(
                select(ProfileFact)
                .where(
                    ProfileFact.candidate_profile_id == candidate_profile.id,
                    ProfileFact.visibility == "public",
                    ProfileFact.verification_status == "published",
                )
                .order_by(ProfileFact.created_at.asc())
            )
        )
        if session is not None
        else [
            fact
            for fact in candidate_profile.facts
            if fact.visibility == "public" and fact.verification_status == "published"
        ]
    )
    published_facts = [
        {
            "id": fact.id,
            "claim": fact.claim,
            "category": fact.fact_type,
            "source": fact.source,
            "visibility": fact.visibility,
            "verificationStatus": fact.verification_status,
        }
        for fact in fact_rows
    ]
    published_role_target = latest_published_public_role_target(candidate_profile)
    published_skills = published_public_skills(candidate_profile.id, candidate_profile)
    published_experiences = published_public_experience(candidate_profile.id, candidate_profile)
    published_links = published_public_links(candidate_profile.id, candidate_profile)

    return {
        "id": candidate_profile.id,
        "slug": candidate_profile.slug,
        "displayName": candidate_profile.display_name,
        "headline": candidate_profile.headline,
        "summary": candidate_profile.summary,
        "profileStatus": candidate_profile.profile_status,
        "updatedAt": candidate_profile.updated_at.isoformat(),
        "facts": published_facts,
        "targetRoleIntent": serialize_public_role_target(published_role_target),
        "skillClaims": [serialize_public_skill(skill) for skill in published_skills],
        "experienceAndProjects": [serialize_public_experience(item) for item in published_experiences],
        "evidenceLinks": [serialize_public_link(item) for item in published_links],
        "hasPublishedPublicContent": bool(
            published_facts or published_skills or published_experiences or published_links or published_role_target
        ),
    }


def candidate_profile_to_published_dict(candidate_profile: CandidateProfile) -> dict[str, Any]:
    session = object_session(candidate_profile)
    fact_rows = (
        list(
            session.scalars(
                select(ProfileFact)
                .where(
                    ProfileFact.candidate_profile_id == candidate_profile.id,
                    ProfileFact.visibility.in_(("private", "public")),
                    ProfileFact.verification_status == "published",
                )
                .order_by(ProfileFact.created_at.asc())
            )
        )
        if session is not None
        else [fact for fact in candidate_profile.facts if fact.verification_status == "published"]
    )
    published_facts = [
        {
            "id": fact.id,
            "claim": fact.claim,
            "category": fact.fact_type,
            "source": fact.source,
            "visibility": fact.visibility,
            "verificationStatus": fact.verification_status,
        }
        for fact in fact_rows
    ]
    published_role_target = latest_published_role_target(candidate_profile)
    published_skills = published_skills_for_internal_context(candidate_profile.id, candidate_profile)
    published_experiences = published_experience_for_internal_context(candidate_profile.id, candidate_profile)
    published_links = published_links_for_internal_context(candidate_profile.id, candidate_profile)

    return {
        "id": candidate_profile.id,
        "slug": candidate_profile.slug,
        "displayName": candidate_profile.display_name,
        "headline": candidate_profile.headline,
        "summary": candidate_profile.summary,
        "profileStatus": candidate_profile.profile_status,
        "updatedAt": candidate_profile.updated_at.isoformat(),
        "facts": published_facts,
        "targetRoleIntent": serialize_published_role_target(published_role_target),
        "skillClaims": [serialize_public_skill(skill) for skill in published_skills],
        "experienceAndProjects": [serialize_public_experience(item) for item in published_experiences],
        "evidenceLinks": [serialize_public_link(item) for item in published_links],
        "hasPublishedPublicContent": any(
            item.get("visibility") == "public"
            for item in [*published_facts, *[serialize_public_skill(skill) for skill in published_skills], *[serialize_public_experience(item) for item in published_experiences], *[serialize_public_link(item) for item in published_links]]
        ),
    }


def candidate_profile_to_private_context_dict(candidate_profile: CandidateProfile) -> dict[str, Any]:
    """Private command-center context: active published knowledge plus labeled inactive review context."""
    published = candidate_profile_to_published_dict(candidate_profile)
    session = object_session(candidate_profile)
    draft_items: list[dict[str, Any]] = []
    archived_items: list[dict[str, Any]] = []
    if session is not None:
        draft_items = [
            *[
                {
                    "type": "fact",
                    "id": item.id,
                    "claim": item.claim,
                    "category": item.fact_type,
                    "visibility": item.suggested_visibility,
                    "state": "draft",
                }
                for item in session.scalars(
                    select(ProfileFactDraft)
                    .where(
                        ProfileFactDraft.candidate_profile_id == candidate_profile.id,
                        ProfileFactDraft.review_status.in_(("draft", "needs_review", "candidate_approved")),
                    )
                    .order_by(ProfileFactDraft.created_at.asc())
                )
            ],
            *[
                {
                    "type": "skill",
                    "id": item.id,
                    "skill": item.skill_name,
                    "category": item.skill_category,
                    "visibility": item.visibility,
                    "state": "draft",
                }
                for item in session.scalars(
                    select(SkillClaim)
                    .where(
                        SkillClaim.candidate_profile_id == candidate_profile.id,
                        SkillClaim.publication_status != "published",
                        SkillClaim.verification_status.in_(("draft", "needs_review", "candidate_approved", "reviewed")),
                    )
                    .order_by(SkillClaim.created_at.asc())
                )
            ],
            *[
                {
                    "type": "experience",
                    "id": item.id,
                    "title": item.title,
                    "organization": item.organization,
                    "visibility": item.visibility,
                    "state": "draft",
                }
                for item in session.scalars(
                    select(ExperienceProjectDraft)
                    .where(
                        ExperienceProjectDraft.candidate_profile_id == candidate_profile.id,
                        ExperienceProjectDraft.publication_status != "published",
                        ExperienceProjectDraft.review_status.in_(("draft", "needs_review", "candidate_approved", "reviewed")),
                    )
                    .order_by(ExperienceProjectDraft.created_at.asc())
                )
            ],
        ]
        archived_items = [
            *[
                {"type": "fact", "id": item.id, "claim": item.claim, "category": item.fact_type, "state": "archived"}
                for item in session.scalars(
                    select(ProfileFactDraft)
                    .where(
                        ProfileFactDraft.candidate_profile_id == candidate_profile.id,
                        ProfileFactDraft.review_status == "rejected",
                    )
                    .order_by(ProfileFactDraft.created_at.asc())
                )
            ],
            *[
                {"type": "fact", "id": item.id, "claim": item.claim, "category": item.fact_type, "state": "archived"}
                for item in session.scalars(
                    select(ProfileFact)
                    .where(
                        ProfileFact.candidate_profile_id == candidate_profile.id,
                        ProfileFact.verification_status == "rejected",
                    )
                    .order_by(ProfileFact.created_at.asc())
                )
            ],
            *[
                {"type": "skill", "id": item.id, "skill": item.skill_name, "category": item.skill_category, "state": "archived"}
                for item in session.scalars(
                    select(SkillClaim)
                    .where(
                        SkillClaim.candidate_profile_id == candidate_profile.id,
                        SkillClaim.verification_status == "rejected",
                    )
                    .order_by(SkillClaim.created_at.asc())
                )
            ],
            *[
                {"type": "experience", "id": item.id, "title": item.title, "organization": item.organization, "state": "archived"}
                for item in session.scalars(
                    select(ExperienceProjectDraft)
                    .where(
                        ExperienceProjectDraft.candidate_profile_id == candidate_profile.id,
                        ExperienceProjectDraft.review_status == "rejected",
                    )
                    .order_by(ExperienceProjectDraft.created_at.asc())
                )
            ],
            *[
                {"type": "evidence", "id": item.id, "label": item.label, "url": item.uri, "state": "archived"}
                for item in session.scalars(
                    select(EvidenceArtifact)
                    .where(
                        EvidenceArtifact.candidate_profile_id == candidate_profile.id,
                        EvidenceArtifact.review_status == "rejected",
                    )
                    .order_by(EvidenceArtifact.created_at.asc())
                )
            ],
            *[
                {"type": "target-role", "id": item.id, "targetTitles": item.target_titles, "state": "archived"}
                for item in session.scalars(
                    select(RoleTarget)
                    .where(
                        RoleTarget.candidate_profile_id == candidate_profile.id,
                        RoleTarget.review_status == "rejected",
                    )
                    .order_by(RoleTarget.created_at.asc())
                )
            ],
        ]

    public_items, internal_items = partition_published_items(published)
    return {
        "profile_basics": {
            "id": candidate_profile.id,
            "slug": candidate_profile.slug,
            "displayName": candidate_profile.display_name,
            "headline": candidate_profile.headline,
            "summary": candidate_profile.summary,
            "profileStatus": candidate_profile.profile_status,
        },
        "targets": published.get("targetRoleIntent") or {},
        "published_public_items": public_items,
        "published_internal_items": internal_items,
        "draft_items": draft_items,
        "archived_suppressed_items_summary": archived_items[:25],
    }


def partition_published_items(published_profile: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    public_items: list[dict[str, Any]] = []
    internal_items: list[dict[str, Any]] = []
    for collection_name in ("facts", "skillClaims", "experienceAndProjects", "evidenceLinks"):
        for item in published_profile.get(collection_name) or []:
            decorated = {"collection": collection_name, **item}
            if item.get("visibility") == "public":
                public_items.append(decorated)
            else:
                internal_items.append(decorated)
    target = published_profile.get("targetRoleIntent") or {}
    if target:
        decorated_target = {"collection": "targetRoleIntent", **target}
        if target.get("visibility") == "public":
            public_items.append(decorated_target)
        else:
            internal_items.append(decorated_target)
    return public_items, internal_items


def get_candidate_profile_by_slug(session: Session, slug: str, *, tenant_id: str | None = None) -> CandidateProfile | None:
    statement = select(CandidateProfile).where(CandidateProfile.slug == slug)
    if tenant_id is not None:
        statement = statement.where(CandidateProfile.tenant_id == tenant_id)
    return session.scalar(statement.order_by(CandidateProfile.created_at.asc()).limit(1))


def get_candidate_profile_by_hostname(session: Session, hostname: str) -> CandidateProfile | None:
    normalized_hostname = hostname.lower().strip()
    return session.scalar(
        select(CandidateProfile)
        .join(Domain, Domain.candidate_profile_id == CandidateProfile.id)
        .where(Domain.hostname == normalized_hostname)
    )


def get_candidate_profile_by_tenant_or_profile_slug(session: Session, slug: str) -> CandidateProfile | None:
    normalized_slug = slug.strip().lower()
    tenant = session.scalar(select(Tenant).where(Tenant.slug == normalized_slug))
    if tenant is not None:
        profiles = list(
            session.scalars(
                select(CandidateProfile)
                .where(CandidateProfile.tenant_id == tenant.id)
                .order_by(CandidateProfile.slug == normalized_slug, CandidateProfile.created_at.asc())
                .limit(2)
            )
        )
        if len(profiles) == 1:
            return profiles[0]
        exact = [profile for profile in profiles if profile.slug == normalized_slug]
        return exact[0] if len(exact) == 1 else None

    profiles = list(
        session.scalars(
            select(CandidateProfile)
            .where(CandidateProfile.slug == normalized_slug)
            .order_by(CandidateProfile.created_at.asc())
            .limit(2)
        )
    )
    return profiles[0] if len(profiles) == 1 else None


def latest_published_public_role_target(candidate_profile: CandidateProfile) -> RoleTarget | None:
    session = object_session(candidate_profile)
    if session is None:
        return None
    return session.scalar(
        select(RoleTarget)
        .where(
            RoleTarget.candidate_profile_id == candidate_profile.id,
            RoleTarget.visibility == "public",
            RoleTarget.publication_status == "published",
            RoleTarget.is_active.is_(True),
        )
        .order_by(RoleTarget.updated_at.desc(), RoleTarget.created_at.desc())
    )


def latest_published_role_target(candidate_profile: CandidateProfile) -> RoleTarget | None:
    session = object_session(candidate_profile)
    if session is None:
        return None
    return session.scalar(
        select(RoleTarget)
        .where(
            RoleTarget.candidate_profile_id == candidate_profile.id,
            RoleTarget.visibility.in_(("private", "public")),
            RoleTarget.publication_status == "published",
            RoleTarget.is_active.is_(True),
        )
        .order_by(RoleTarget.updated_at.desc(), RoleTarget.created_at.desc())
    )


def published_public_skills(candidate_profile_id: str, candidate_profile: CandidateProfile) -> list[SkillClaim]:
    session = object_session(candidate_profile)
    if session is None:
        return []
    return list(
        session.scalars(
            select(SkillClaim)
            .where(
                SkillClaim.candidate_profile_id == candidate_profile_id,
                SkillClaim.visibility == "public",
                SkillClaim.publication_status == "published",
                SkillClaim.verification_status == "published",
            )
            .order_by(SkillClaim.skill_category.asc(), SkillClaim.skill_name.asc())
        )
    )


def published_skills_for_internal_context(candidate_profile_id: str, candidate_profile: CandidateProfile) -> list[SkillClaim]:
    session = object_session(candidate_profile)
    if session is None:
        return []
    return list(
        session.scalars(
            select(SkillClaim)
            .where(
                SkillClaim.candidate_profile_id == candidate_profile_id,
                SkillClaim.visibility.in_(("private", "public")),
                SkillClaim.publication_status == "published",
                SkillClaim.verification_status == "published",
            )
            .order_by(SkillClaim.skill_category.asc(), SkillClaim.skill_name.asc())
        )
    )


def published_public_experience(candidate_profile_id: str, candidate_profile: CandidateProfile) -> list[ExperienceProjectDraft]:
    session = object_session(candidate_profile)
    if session is None:
        return []
    return list(
        session.scalars(
            select(ExperienceProjectDraft)
            .where(
                ExperienceProjectDraft.candidate_profile_id == candidate_profile_id,
                ExperienceProjectDraft.visibility == "public",
                ExperienceProjectDraft.publication_status == "published",
            )
            .order_by(ExperienceProjectDraft.created_at.asc())
        )
    )


def published_experience_for_internal_context(candidate_profile_id: str, candidate_profile: CandidateProfile) -> list[ExperienceProjectDraft]:
    session = object_session(candidate_profile)
    if session is None:
        return []
    return list(
        session.scalars(
            select(ExperienceProjectDraft)
            .where(
                ExperienceProjectDraft.candidate_profile_id == candidate_profile_id,
                ExperienceProjectDraft.visibility.in_(("private", "public")),
                ExperienceProjectDraft.publication_status == "published",
            )
            .order_by(ExperienceProjectDraft.created_at.asc())
        )
    )


def published_public_links(candidate_profile_id: str, candidate_profile: CandidateProfile) -> list[EvidenceArtifact]:
    session = object_session(candidate_profile)
    if session is None:
        return []
    return list(
        session.scalars(
            select(EvidenceArtifact)
            .where(
                EvidenceArtifact.candidate_profile_id == candidate_profile_id,
                EvidenceArtifact.visibility == "public",
                EvidenceArtifact.publication_status == "published",
            )
            .order_by(EvidenceArtifact.created_at.asc())
        )
    )


def published_links_for_internal_context(candidate_profile_id: str, candidate_profile: CandidateProfile) -> list[EvidenceArtifact]:
    session = object_session(candidate_profile)
    if session is None:
        return []
    return list(
        session.scalars(
            select(EvidenceArtifact)
            .where(
                EvidenceArtifact.candidate_profile_id == candidate_profile_id,
                EvidenceArtifact.visibility.in_(("private", "public")),
                EvidenceArtifact.publication_status == "published",
            )
            .order_by(EvidenceArtifact.created_at.asc())
        )
    )


def serialize_public_role_target(role_target: RoleTarget | None) -> dict[str, Any]:
    if role_target is None:
        return {}
    constraints = role_target.constraints if isinstance(role_target.constraints, dict) else {}
    return {
        "id": role_target.id,
        "targetTitles": role_target.target_titles,
        "roleFamilies": role_target.role_families,
        "preferredLocations": role_target.preferred_locations,
        "workModes": role_target.work_modes,
        "domainsOrIndustries": constraints.get("domainsOrIndustries"),
        "visibility": role_target.visibility,
        "publicationStatus": role_target.publication_status,
    }


def serialize_published_role_target(role_target: RoleTarget | None) -> dict[str, Any]:
    if role_target is None:
        return {}
    return {
        **serialize_public_role_target(role_target),
        "id": role_target.id,
        "visibility": role_target.visibility,
        "publicationStatus": role_target.publication_status,
    }


def serialize_public_skill(skill: SkillClaim) -> dict[str, Any]:
    return {
        "id": skill.id,
        "skill": skill.skill_name,
        "category": skill.skill_category,
        "evidence": skill.evidence_summary,
        "yearsMin": skill.years_min,
        "yearsMax": skill.years_max,
        "visibility": skill.visibility,
        "verificationStatus": skill.verification_status,
        "publicationStatus": skill.publication_status,
    }


def serialize_public_experience(item: ExperienceProjectDraft) -> dict[str, Any]:
    structured_value = item.structured_value if isinstance(item.structured_value, dict) else {}
    return {
        "id": item.id,
        "itemType": structured_value.get("itemType") or "experience",
        "title": item.title,
        "organization": item.organization,
        "startDate": item.start_date or structured_value.get("startDate"),
        "endDate": item.end_date or structured_value.get("endDate"),
        "location": item.location or structured_value.get("location"),
        "summary": item.summary,
        "bullets": structured_value.get("bullets") if isinstance(structured_value.get("bullets"), list) else [],
        "visibility": item.visibility,
        "publicationStatus": item.publication_status,
    }


def serialize_public_link(item: EvidenceArtifact) -> dict[str, Any]:
    return {
        "id": item.id,
        "label": item.label,
        "url": item.uri or "",
        "visibility": item.visibility,
        "publicationStatus": item.publication_status,
    }
