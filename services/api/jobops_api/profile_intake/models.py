from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from .intake_mode import RESUME_INTAKE_CAPACITY


Source = Literal["chat", "resume", "model"]
GeneratedStatus = Literal["draft", "needs_review"]
ExperienceItemType = Literal["experience", "project", "education", "certification"]
WorkMode = Literal["remote", "hybrid", "onsite", "flexible"]


class ApiModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class ProfileIntakeExtractRequest(ApiModel):
    latest_user_message: str = Field(
        min_length=1,
        validation_alias=AliasChoices("latest_user_message", "latestUserMessage"),
        serialization_alias="latest_user_message",
    )
    existing_draft: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("existing_draft", "existingDraft"),
        serialization_alias="existing_draft",
    )
    candidate_profile_slug: str | None = Field(
        default=None,
        validation_alias=AliasChoices("candidate_profile_slug", "candidateProfileSlug"),
        serialization_alias="candidate_profile_slug",
        max_length=120,
    )


class TargetRoleIntent(ApiModel):
    target_titles: str | None = Field(default=None, alias="targetTitles", max_length=200)
    target_role_families: str | None = Field(default=None, alias="targetRoleFamilies", max_length=200)
    preferred_work_mode: WorkMode | None = Field(default=None, alias="preferredWorkMode")
    preferred_locations: str | None = Field(default=None, alias="preferredLocations", max_length=200)
    domains_or_industries: str | None = Field(default=None, alias="domainsOrIndustries", max_length=200)
    constraints: str | None = Field(default=None, max_length=200)


class GeneratedItem(ApiModel):
    source: Source
    status: GeneratedStatus
    visibility: Literal["private"]
    published: Literal[False]


class ProfileBasics(ApiModel):
    display_name: str | None = Field(default=None, alias="displayName", max_length=200)
    headline: str | None = Field(default=None, max_length=300)
    summary: str | None = Field(default=None, max_length=4000)
    email_address: str | None = Field(default=None, alias="emailAddress", max_length=320)
    telephone_number: str | None = Field(default=None, alias="telephoneNumber", max_length=80)
    calendly_link: str | None = Field(default=None, alias="calendlyLink", max_length=500)
    current_location: str | None = Field(default=None, alias="currentLocation", max_length=200)
    mailing_address: str | None = Field(default=None, alias="mailingAddress", max_length=1000)


class DraftFact(GeneratedItem):
    id: str | None = Field(default=None, max_length=120)
    claim: str = Field(max_length=240)
    category: str | None = Field(default=None, max_length=120)


class SkillClaim(GeneratedItem):
    id: str | None = Field(default=None, max_length=120)
    skill: str = Field(max_length=120)
    category: str | None = Field(default=None, max_length=120)
    evidence: str | None = Field(default=None, max_length=240)
    years_min: int | None = Field(default=None, alias="yearsMin", ge=0, le=80)
    years_max: int | None = Field(default=None, alias="yearsMax", ge=0, le=80)


class ExperienceAndProject(GeneratedItem):
    id: str | None = Field(default=None, max_length=120)
    item_type: ExperienceItemType = Field(default="experience", alias="itemType")
    title: str = Field(max_length=200)
    organization: str | None = Field(default=None, max_length=200)
    start_date: str | None = Field(default=None, alias="startDate", max_length=80)
    end_date: str | None = Field(default=None, alias="endDate", max_length=80)
    location: str | None = Field(default=None, max_length=160)
    summary: str = Field(max_length=320)
    bullets: list[str] = Field(default_factory=list, max_length=12)


class EvidenceLink(GeneratedItem):
    id: str | None = Field(default=None, max_length=120)
    url: str = Field(max_length=1000)
    label: str | None = Field(default=None, max_length=200)


class UpdatedDraftProfile(ApiModel):
    profile_basics: ProfileBasics = Field(default_factory=ProfileBasics, alias="profileBasics")
    target_role_intent: TargetRoleIntent = Field(alias="targetRoleIntent")
    draft_facts: list[DraftFact] = Field(alias="draftFacts", max_length=RESUME_INTAKE_CAPACITY.draft_facts)
    skill_claims: list[SkillClaim] = Field(alias="skillClaims", max_length=RESUME_INTAKE_CAPACITY.skill_claims)
    experience_and_projects: list[ExperienceAndProject] = Field(
        alias="experienceAndProjects",
        max_length=RESUME_INTAKE_CAPACITY.experience_and_projects,
    )
    evidence_links: list[EvidenceLink] = Field(alias="evidenceLinks", max_length=RESUME_INTAKE_CAPACITY.evidence_links)


class RemovedDraftItems(ApiModel):
    draft_fact_ids: list[str] = Field(default_factory=list, alias="draftFactIds", max_length=80)
    skill_claim_ids: list[str] = Field(default_factory=list, alias="skillClaimIds", max_length=80)
    experience_and_project_ids: list[str] = Field(default_factory=list, alias="experienceAndProjectIds", max_length=80)
    evidence_link_ids: list[str] = Field(default_factory=list, alias="evidenceLinkIds", max_length=80)
    target_role_intent_fields: list[str] = Field(default_factory=list, alias="targetRoleIntentFields", max_length=20)


class ProfileIntakeOutput(ApiModel):
    assistant_message: str = Field(alias="assistantMessage", max_length=400)
    updated_draft_profile: UpdatedDraftProfile = Field(alias="updatedDraftProfile")
    clarifying_questions: list[str] = Field(
        alias="clarifyingQuestions",
        max_length=RESUME_INTAKE_CAPACITY.clarifying_questions,
    )
    change_summary: list[str] = Field(alias="changeSummary", max_length=RESUME_INTAKE_CAPACITY.change_summary)
    no_change_reason: str | None = Field(default=None, alias="noChangeReason", max_length=300)
    removed_items: RemovedDraftItems = Field(default_factory=RemovedDraftItems, alias="removedItems")


SAFE_VALIDATION_ERROR = "The model returned malformed profile intake data. No draft data was applied."
