from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import AuthContext, require_auth_context
from .db.models import (
    CandidateProfile,
    EvidenceArtifact,
    ExperienceProjectDraft,
    ProfileFact,
    ProfileFactDraft,
    RoleTarget,
    SkillClaim,
)
from .db.session import get_db_session
from .profile_intake.persistence import get_latest_profile_draft_snapshot
from .profiles import candidate_profile_to_public_dict, candidate_profile_to_published_dict
from .security import require_internal_api_key


router = APIRouter(prefix="/v1/profile", tags=["profile"], dependencies=[Depends(require_internal_api_key)])

DraftItemType = Literal["fact", "skill", "experience", "evidence", "target-role"]
PublishedItemType = DraftItemType


class ProfileFieldsUpdate(BaseModel):
    display_name: str | None = Field(default=None, alias="displayName", max_length=200)
    headline: str | None = Field(default=None, max_length=300)
    summary: str | None = Field(default=None, max_length=4000)


class DraftItemUpdate(BaseModel):
    claim: str | None = Field(default=None, max_length=1200)
    category: str | None = Field(default=None, max_length=120)
    skill: str | None = Field(default=None, max_length=160)
    evidence: str | None = Field(default=None, max_length=1000)
    title: str | None = Field(default=None, max_length=200)
    organization: str | None = Field(default=None, max_length=200)
    summary: str | None = Field(default=None, max_length=1200)
    url: str | None = Field(default=None, max_length=1000)
    label: str | None = Field(default=None, max_length=255)
    visibility: Literal["private", "public"] | None = None
    review_status: Literal["draft", "needs_review", "candidate_approved", "reviewed", "rejected"] | None = Field(
        default=None,
        alias="reviewStatus",
    )
    publish_visibility: Literal["private", "public"] | None = Field(default=None, alias="publishVisibility")


class PublishedItemUpdate(BaseModel):
    visibility: Literal["private", "public"] | None = None
    archive: bool = False


@router.get("/current")
def get_current_profile(session: Session = Depends(get_db_session), auth: AuthContext = Depends(require_auth_context)) -> dict[str, Any]:
    return current_profile_payload(session, auth.candidate_profile, auth.tenant.slug)


@router.patch("/current")
def update_current_profile(
    request: ProfileFieldsUpdate,
    session: Session = Depends(get_db_session),
    auth: AuthContext = Depends(require_auth_context),
) -> dict[str, Any]:
    profile = auth.candidate_profile
    if request.display_name is not None:
        profile.display_name = required_trimmed(request.display_name, "displayName")
    if request.headline is not None:
        profile.headline = required_trimmed(request.headline, "headline")
    if request.summary is not None:
        profile.summary = request.summary.strip()
    session.commit()
    return current_profile_payload(session, profile, auth.tenant.slug)


@router.patch("/draft-items/{item_type}/{item_id}")
def update_draft_item(
    item_type: DraftItemType,
    item_id: str,
    request: DraftItemUpdate,
    session: Session = Depends(get_db_session),
    auth: AuthContext = Depends(require_auth_context),
) -> dict[str, Any]:
    profile = auth.candidate_profile
    item = get_owned_draft_item(session, profile.id, item_type, item_id)

    if isinstance(item, ProfileFactDraft):
        if request.claim is not None:
            item.claim = required_trimmed(request.claim, "claim")
        if request.category is not None:
            item.fact_type = required_trimmed(request.category, "category")
        if request.visibility is not None:
            item.suggested_visibility = request.visibility
        if request.review_status is not None:
            item.review_status = request.review_status
    elif isinstance(item, SkillClaim):
        if request.skill is not None:
            item.skill_name = required_trimmed(request.skill, "skill")
        if request.category is not None:
            item.skill_category = required_trimmed(request.category, "category")
        if request.evidence is not None:
            item.evidence_summary = request.evidence.strip()
        if request.visibility is not None:
            item.visibility = request.visibility
        if request.review_status is not None:
            item.verification_status = request.review_status
    elif isinstance(item, ExperienceProjectDraft):
        if request.title is not None:
            item.title = required_trimmed(request.title, "title")
        if request.organization is not None:
            item.organization = request.organization.strip() or None
        if request.summary is not None:
            item.summary = required_trimmed(request.summary, "summary")
        if request.visibility is not None:
            item.visibility = request.visibility
        if request.review_status is not None:
            item.review_status = request.review_status
    elif isinstance(item, EvidenceArtifact):
        if request.url is not None:
            item.uri = request.url.strip()
        if request.label is not None:
            item.label = required_trimmed(request.label, "label")
        if request.visibility is not None:
            item.visibility = request.visibility
        if request.review_status is not None:
            item.review_status = request.review_status
    else:
        if request.visibility is not None:
            item.visibility = request.visibility
        if request.review_status is not None:
            item.review_status = request.review_status

    if request.publish_visibility is not None:
        publish_single_item_as(session, profile, item_type, item, request.publish_visibility)

    session.commit()
    return current_profile_payload(session, profile, auth.tenant.slug)


@router.patch("/published-items/{item_type}/{item_id}")
def update_published_item(
    item_type: PublishedItemType,
    item_id: str,
    request: PublishedItemUpdate,
    session: Session = Depends(get_db_session),
    auth: AuthContext = Depends(require_auth_context),
) -> dict[str, Any]:
    profile = auth.candidate_profile
    item = get_owned_published_item(session, profile.id, item_type, item_id)

    if request.visibility is not None:
        set_item_visibility(item, request.visibility)
    if request.archive:
        archive_published_item(item)

    session.commit()
    return current_profile_payload(session, profile, auth.tenant.slug)


@router.post("/publish")
def publish_current_profile(
    session: Session = Depends(get_db_session),
    auth: AuthContext = Depends(require_auth_context),
) -> dict[str, Any]:
    profile = auth.candidate_profile
    published_count = publish_approved_items(session, profile)
    if published_content_count(session, profile.id) > 0:
        profile.profile_status = "published"
    session.commit()
    return {
        **current_profile_payload(session, profile, auth.tenant.slug),
        "publishedCount": published_count,
    }


def current_profile_payload(session: Session, profile: CandidateProfile, tenant_slug: str) -> dict[str, Any]:
    return {
        "ok": True,
        "result": {
            "profile": {
                "id": profile.id,
                "slug": profile.slug,
                "displayName": profile.display_name,
                "headline": profile.headline,
                "summary": profile.summary,
                "profileStatus": profile.profile_status,
                "tenantSlug": tenant_slug,
            },
            "draft": get_latest_profile_draft_snapshot(session, profile),
            "publishedProfile": candidate_profile_to_published_dict(profile),
            "publicProfile": candidate_profile_to_public_dict(profile),
            "publicPortfolioPath": f"/portfolio/{tenant_slug}",
            "publishedItemCount": published_content_count(session, profile.id),
            "publishedPublicItemCount": public_content_count(session, profile.id),
            "archivedItemCount": archived_content_count(session, profile.id),
        },
    }


def get_owned_draft_item(session: Session, candidate_profile_id: str, item_type: DraftItemType, item_id: str):
    model = {
        "fact": ProfileFactDraft,
        "skill": SkillClaim,
        "experience": ExperienceProjectDraft,
        "evidence": EvidenceArtifact,
        "target-role": RoleTarget,
    }[item_type]
    item = session.scalar(
        select(model).where(
            model.id == item_id,
            model.candidate_profile_id == candidate_profile_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Draft profile item not found.")
    return item


def get_owned_published_item(session: Session, candidate_profile_id: str, item_type: PublishedItemType, item_id: str):
    model = {
        "fact": ProfileFact,
        "skill": SkillClaim,
        "experience": ExperienceProjectDraft,
        "evidence": EvidenceArtifact,
        "target-role": RoleTarget,
    }[item_type]
    item = session.scalar(
        select(model).where(
            model.id == item_id,
            model.candidate_profile_id == candidate_profile_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Published profile item not found.")
    return item


def set_item_visibility(item, visibility: Literal["private", "public"]) -> None:
    if isinstance(item, ProfileFact):
        if item.verification_status != "published":
            raise HTTPException(status_code=400, detail="Only published facts can change visibility.")
        item.visibility = visibility
        return
    if isinstance(item, (SkillClaim, ExperienceProjectDraft, EvidenceArtifact, RoleTarget)):
        if getattr(item, "publication_status", None) != "published":
            raise HTTPException(status_code=400, detail="Only published items can change visibility.")
        item.visibility = visibility
        return
    raise HTTPException(status_code=400, detail="Unsupported profile item type.")


def archive_published_item(item) -> None:
    # Archived items are not active JobOps knowledge and are excluded from public serialization.
    if isinstance(item, ProfileFact):
        item.visibility = "private"
        item.verification_status = "rejected"
    elif isinstance(item, SkillClaim):
        item.visibility = "private"
        item.verification_status = "rejected"
        item.publication_status = "archived"
    elif isinstance(item, ExperienceProjectDraft):
        item.visibility = "private"
        item.review_status = "rejected"
        item.publication_status = "archived"
    elif isinstance(item, EvidenceArtifact):
        item.visibility = "private"
        item.review_status = "rejected"
        item.publication_status = "archived"
    elif isinstance(item, RoleTarget):
        item.visibility = "private"
        item.review_status = "rejected"
        item.publication_status = "archived"
        item.is_active = False


def publish_approved_items(session: Session, profile: CandidateProfile) -> int:
    count = 0
    for fact in session.scalars(
        select(ProfileFactDraft).where(
            ProfileFactDraft.candidate_profile_id == profile.id,
            ProfileFactDraft.review_status.in_(("candidate_approved", "reviewed")),
        )
    ):
        structured_value = fact.structured_value if isinstance(fact.structured_value, dict) else {}
        if structured_value.get("published") is True:
            continue
        published_fact = ProfileFact(
            candidate_profile_id=profile.id,
            fact_type=fact.fact_type,
            claim=fact.claim,
            structured_value={"derivedFromDraftFactId": fact.id},
            source=fact.source,
            visibility=fact.suggested_visibility,
            verification_status="published",
        )
        session.add(published_fact)
        session.flush()
        fact.structured_value = {**structured_value, "published": True, "publishedFactId": published_fact.id}
        count += 1

    for skill in session.scalars(
        select(SkillClaim).where(
            SkillClaim.candidate_profile_id == profile.id,
            SkillClaim.verification_status.in_(("candidate_approved", "reviewed")),
        )
    ):
        if skill.publication_status != "published":
            count += 1
        skill.verification_status = "published"
        skill.publication_status = "published"

    for item in session.scalars(
        select(ExperienceProjectDraft).where(
            ExperienceProjectDraft.candidate_profile_id == profile.id,
            ExperienceProjectDraft.review_status.in_(("candidate_approved", "reviewed")),
        )
    ):
        if item.publication_status != "published":
            count += 1
        item.review_status = "reviewed"
        item.publication_status = "published"

    for link in session.scalars(
        select(EvidenceArtifact).where(
            EvidenceArtifact.candidate_profile_id == profile.id,
            EvidenceArtifact.review_status.in_(("candidate_approved", "reviewed")),
        )
    ):
        if link.publication_status != "published":
            count += 1
        link.review_status = "reviewed"
        link.publication_status = "published"

    return count


def publish_single_item_as(
    session: Session,
    profile: CandidateProfile,
    item_type: DraftItemType,
    item,
    visibility: Literal["private", "public"],
) -> None:
    if isinstance(item, ProfileFactDraft):
        item.suggested_visibility = visibility
        item.review_status = "reviewed"
        structured_value = item.structured_value if isinstance(item.structured_value, dict) else {}
        if structured_value.get("published") is not True:
            published_fact = ProfileFact(
                candidate_profile_id=profile.id,
                fact_type=item.fact_type,
                claim=item.claim,
                structured_value={"derivedFromDraftFactId": item.id},
                source=item.source,
                visibility=visibility,
                verification_status="published",
            )
            session.add(published_fact)
            session.flush()
            item.structured_value = {**structured_value, "published": True, "publishedFactId": published_fact.id}
    elif isinstance(item, SkillClaim):
        item.visibility = visibility
        item.verification_status = "published"
        item.publication_status = "published"
    elif isinstance(item, ExperienceProjectDraft):
        item.visibility = visibility
        item.review_status = "reviewed"
        item.publication_status = "published"
    elif isinstance(item, EvidenceArtifact):
        item.visibility = visibility
        item.review_status = "reviewed"
        item.publication_status = "published"
    elif isinstance(item, RoleTarget):
        item.visibility = visibility
        item.review_status = "reviewed"
        item.publication_status = "published"
    if published_content_count(session, profile.id) > 0:
        profile.profile_status = "published"


def public_content_count(session: Session, candidate_profile_id: str) -> int:
    fact_count = len(
        list(
            session.scalars(
                select(ProfileFact.id).where(
                    ProfileFact.candidate_profile_id == candidate_profile_id,
                    ProfileFact.visibility == "public",
                    ProfileFact.verification_status == "published",
                )
            )
        )
    )
    skill_count = len(
        list(
            session.scalars(
                select(SkillClaim.id).where(
                    SkillClaim.candidate_profile_id == candidate_profile_id,
                    SkillClaim.visibility == "public",
                    SkillClaim.verification_status == "published",
                    SkillClaim.publication_status == "published",
                )
            )
        )
    )
    experience_count = len(
        list(
            session.scalars(
                select(ExperienceProjectDraft.id).where(
                    ExperienceProjectDraft.candidate_profile_id == candidate_profile_id,
                    ExperienceProjectDraft.visibility == "public",
                    ExperienceProjectDraft.publication_status == "published",
                )
            )
        )
    )
    link_count = len(
        list(
            session.scalars(
                select(EvidenceArtifact.id).where(
                    EvidenceArtifact.candidate_profile_id == candidate_profile_id,
                    EvidenceArtifact.visibility == "public",
                    EvidenceArtifact.publication_status == "published",
                )
            )
        )
    )
    target_count = len(
        list(
            session.scalars(
                select(RoleTarget.id).where(
                    RoleTarget.candidate_profile_id == candidate_profile_id,
                    RoleTarget.visibility == "public",
                    RoleTarget.publication_status == "published",
                    RoleTarget.is_active.is_(True),
                )
            )
        )
    )
    return fact_count + skill_count + experience_count + link_count + target_count


def published_content_count(session: Session, candidate_profile_id: str) -> int:
    fact_count = len(
        list(
            session.scalars(
                select(ProfileFact.id).where(
                    ProfileFact.candidate_profile_id == candidate_profile_id,
                    ProfileFact.visibility.in_(("private", "public")),
                    ProfileFact.verification_status == "published",
                )
            )
        )
    )
    skill_count = len(
        list(
            session.scalars(
                select(SkillClaim.id).where(
                    SkillClaim.candidate_profile_id == candidate_profile_id,
                    SkillClaim.visibility.in_(("private", "public")),
                    SkillClaim.verification_status == "published",
                    SkillClaim.publication_status == "published",
                )
            )
        )
    )
    experience_count = len(
        list(
            session.scalars(
                select(ExperienceProjectDraft.id).where(
                    ExperienceProjectDraft.candidate_profile_id == candidate_profile_id,
                    ExperienceProjectDraft.visibility.in_(("private", "public")),
                    ExperienceProjectDraft.publication_status == "published",
                )
            )
        )
    )
    link_count = len(
        list(
            session.scalars(
                select(EvidenceArtifact.id).where(
                    EvidenceArtifact.candidate_profile_id == candidate_profile_id,
                    EvidenceArtifact.visibility.in_(("private", "public")),
                    EvidenceArtifact.publication_status == "published",
                )
            )
        )
    )
    target_count = len(
        list(
            session.scalars(
                select(RoleTarget.id).where(
                    RoleTarget.candidate_profile_id == candidate_profile_id,
                    RoleTarget.visibility.in_(("private", "public")),
                    RoleTarget.publication_status == "published",
                    RoleTarget.is_active.is_(True),
                )
            )
        )
    )
    return fact_count + skill_count + experience_count + link_count + target_count


def archived_content_count(session: Session, candidate_profile_id: str) -> int:
    fact_count = len(
        list(
            session.scalars(
                select(ProfileFact.id).where(
                    ProfileFact.candidate_profile_id == candidate_profile_id,
                    ProfileFact.verification_status == "rejected",
                )
            )
        )
    )
    draft_fact_count = len(
        list(
            session.scalars(
                select(ProfileFactDraft.id).where(
                    ProfileFactDraft.candidate_profile_id == candidate_profile_id,
                    ProfileFactDraft.review_status == "rejected",
                )
            )
        )
    )
    skill_count = len(
        list(
            session.scalars(
                select(SkillClaim.id).where(
                    SkillClaim.candidate_profile_id == candidate_profile_id,
                    SkillClaim.verification_status == "rejected",
                )
            )
        )
    )
    experience_count = len(
        list(
            session.scalars(
                select(ExperienceProjectDraft.id).where(
                    ExperienceProjectDraft.candidate_profile_id == candidate_profile_id,
                    ExperienceProjectDraft.review_status == "rejected",
                )
            )
        )
    )
    link_count = len(
        list(
            session.scalars(
                select(EvidenceArtifact.id).where(
                    EvidenceArtifact.candidate_profile_id == candidate_profile_id,
                    EvidenceArtifact.review_status == "rejected",
                )
            )
        )
    )
    target_count = len(
        list(
            session.scalars(
                select(RoleTarget.id).where(
                    RoleTarget.candidate_profile_id == candidate_profile_id,
                    RoleTarget.review_status == "rejected",
                )
            )
        )
    )
    return fact_count + draft_fact_count + skill_count + experience_count + link_count + target_count


def required_trimmed(value: str, field_name: str) -> str:
    trimmed = value.strip()
    if not trimmed:
        raise HTTPException(status_code=400, detail=f"{field_name} cannot be empty.")
    return trimmed
