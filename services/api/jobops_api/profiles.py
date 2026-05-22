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
        "hasPublishedPublicContent": bool(published_facts or published_skills or published_experiences or published_links),
    }


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


def serialize_public_role_target(role_target: RoleTarget | None) -> dict[str, Any]:
    if role_target is None:
        return {}
    constraints = role_target.constraints if isinstance(role_target.constraints, dict) else {}
    return {
        "targetTitles": role_target.target_titles,
        "roleFamilies": role_target.role_families,
        "preferredLocations": role_target.preferred_locations,
        "workModes": role_target.work_modes,
        "domainsOrIndustries": constraints.get("domainsOrIndustries"),
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
