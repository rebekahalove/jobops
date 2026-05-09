from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from jobops_api.db.models import CandidateProfile, Domain, Tenant


def seed_public_profile(
    session: Session,
    profile: dict[str, Any],
    *,
    hostname: str | None = None,
) -> CandidateProfile:
    tenant_slug = profile["slug"]
    tenant = session.scalar(select(Tenant).where(Tenant.slug == tenant_slug))
    if tenant is None:
        tenant = Tenant(name=profile["displayName"], slug=tenant_slug)
        session.add(tenant)
        session.flush()

    candidate_profile = session.scalar(
        select(CandidateProfile).where(
            CandidateProfile.tenant_id == tenant.id,
            CandidateProfile.slug == profile["slug"],
        )
    )
    if candidate_profile is None:
        candidate_profile = CandidateProfile(
            tenant_id=tenant.id,
            slug=profile["slug"],
            display_name=profile["displayName"],
            headline=profile["headline"],
            summary=profile["summary"],
            profile_status=profile["profileStatus"],
        )
        session.add(candidate_profile)
    else:
        candidate_profile.display_name = profile["displayName"]
        candidate_profile.headline = profile["headline"]
        candidate_profile.summary = profile["summary"]
        candidate_profile.profile_status = profile["profileStatus"]

    session.flush()

    if hostname:
        normalized_hostname = hostname.lower().strip()
        domain = session.scalar(select(Domain).where(Domain.hostname == normalized_hostname))
        if domain is None:
            session.add(
                Domain(
                    candidate_profile_id=candidate_profile.id,
                    hostname=normalized_hostname,
                    purpose="public_profile",
                    verification_status="pending",
                    is_canonical=True,
                )
            )
        else:
            domain.candidate_profile_id = candidate_profile.id
            domain.purpose = "public_profile"
            domain.is_canonical = True

    return candidate_profile
