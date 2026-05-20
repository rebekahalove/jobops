from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from jobops_api.db.models import CandidateProfile, Domain


def candidate_profile_to_public_dict(candidate_profile: CandidateProfile) -> dict[str, Any]:
    return {
        "id": candidate_profile.id,
        "slug": candidate_profile.slug,
        "displayName": candidate_profile.display_name,
        "headline": candidate_profile.headline,
        "summary": candidate_profile.summary,
        "profileStatus": candidate_profile.profile_status,
        "updatedAt": candidate_profile.updated_at.isoformat(),
        "facts": [
            {
                "id": fact.id,
                "claim": fact.claim,
                "category": fact.fact_type,
                "source": fact.source,
                "visibility": fact.visibility,
                "verificationStatus": fact.verification_status,
            }
            for fact in candidate_profile.facts
            if fact.visibility == "public" and fact.verification_status == "published"
        ],
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
