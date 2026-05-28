from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import CandidateProfile, ProfileIntakeEvent, ProfileIntakeSession
from ..profiles import (
    candidate_profile_to_private_context_dict,
    candidate_profile_to_public_dict,
    candidate_profile_to_published_dict,
)
from .models import ProfileIntakeExtractRequest


class ProfileIntakeContextBundle(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    latest_user_message: str = Field(alias="latestUserMessage")
    conversation_transcript_metadata: list[dict[str, Any]] = Field(
        default_factory=list,
        alias="conversationTranscriptMetadata",
    )
    current_generated_draft_profile: dict[str, Any] = Field(default_factory=dict, alias="currentGeneratedDraftProfile")
    published_private_profile: dict[str, Any] = Field(default_factory=dict, alias="publishedPrivateProfile")
    published_public_profile: dict[str, Any] = Field(default_factory=dict, alias="publishedPublicProfile")
    existing_review_queue: dict[str, Any] = Field(default_factory=dict, alias="existingReviewQueue")
    archived_generated_items_avoidance_context: list[dict[str, Any]] = Field(
        default_factory=list,
        alias="archivedGeneratedItemsAvoidanceContext",
    )
    context_manifest: dict[str, Any] = Field(default_factory=dict, alias="contextManifest")
    resume_document_text: str | None = Field(default=None, alias="resumeDocumentText")
    profile_targets_and_basics: dict[str, Any] = Field(default_factory=dict, alias="profileTargetsAndBasics")
    client_existing_draft: dict[str, Any] | None = Field(default=None, alias="clientExistingDraft")
    authoritative_current_draft_source: str = Field(default="database", alias="authoritativeCurrentDraftSource")
    reconciliation_mode: str = Field(default="respect_archived", alias="reconciliationMode")


def build_profile_intake_context_bundle(
    request: ProfileIntakeExtractRequest,
    *,
    db_session: Session | None,
    candidate_profile: CandidateProfile | None,
    intake_session: ProfileIntakeSession | None,
    authoritative_current_draft: dict[str, Any] | None,
    authoritative_current_draft_source: str,
) -> ProfileIntakeContextBundle:
    current_draft = authoritative_current_draft if isinstance(authoritative_current_draft, dict) else {}
    private_context = candidate_profile_to_private_context_dict(candidate_profile) if candidate_profile is not None else {}
    public_profile = candidate_profile_to_public_dict(candidate_profile) if candidate_profile is not None else {}
    published_profile = candidate_profile_to_published_dict(candidate_profile) if candidate_profile is not None else {}
    transcript_metadata = recent_transcript_metadata(db_session, intake_session)
    active_current_draft = active_generated_draft_context(current_draft)
    archived_avoidance_context = compact_archived_avoidance_context(
        private_context.get("archived_suppressed_items_summary") or []
    )

    bundle = ProfileIntakeContextBundle(
        latestUserMessage=request.latest_user_message,
        conversationTranscriptMetadata=transcript_metadata,
        currentGeneratedDraftProfile=active_current_draft,
        publishedPrivateProfile=published_profile,
        publishedPublicProfile=public_profile,
        existingReviewQueue={
            "draftItems": private_context.get("draft_items") or [],
            "archivedSuppressedItemsSummary": archived_avoidance_context,
        },
        archivedGeneratedItemsAvoidanceContext=archived_avoidance_context,
        resumeDocumentText=None,
        profileTargetsAndBasics={
            "profileBasics": (
                active_current_draft.get("profileBasics")
                if isinstance(active_current_draft.get("profileBasics"), dict)
                else {}
            ),
            "targetRoleIntent": (
                active_current_draft.get("targetRoleIntent")
                if isinstance(active_current_draft.get("targetRoleIntent"), dict)
                else {}
            ),
        },
        clientExistingDraft=request.existing_draft,
        authoritativeCurrentDraftSource=authoritative_current_draft_source,
        reconciliationMode=request.reconciliation_mode,
    )
    return bundle.model_copy(update={"context_manifest": build_context_manifest(bundle)})


def active_generated_draft_context(current_draft: dict[str, Any]) -> dict[str, Any]:
    return {
        "profileBasics": current_draft.get("profileBasics") if isinstance(current_draft.get("profileBasics"), dict) else {},
        "targetRoleIntent": (
            current_draft.get("targetRoleIntent") if active_draft_item(current_draft.get("targetRoleIntent")) else {}
        ),
        "draftFacts": active_draft_items(current_draft.get("draftFacts")),
        "skillClaims": active_draft_items(current_draft.get("skillClaims")),
        "experienceAndProjects": active_draft_items(current_draft.get("experienceAndProjects")),
        "evidenceLinks": active_draft_items(current_draft.get("evidenceLinks")),
    }


def active_draft_items(value: object) -> list[dict[str, Any]]:
    return [item for item in value if active_draft_item(item)] if isinstance(value, list) else []


def active_draft_item(value: object) -> bool:
    return isinstance(value, dict) and value.get("published") is not True and value.get("status") != "rejected"


def compact_archived_avoidance_context(items: list[Any], *, limit: int = 25) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        compacted.append({key: value for key, value in item.items() if key in archived_context_keys() and value})
        if len(compacted) >= limit:
            break
    return compacted


def archived_context_keys() -> set[str]:
    return {
        "type",
        "group",
        "field",
        "value",
        "claim",
        "category",
        "skill",
        "title",
        "organization",
        "label",
        "url",
        "state",
        "archiveReason",
    }


def build_context_manifest(bundle: ProfileIntakeContextBundle) -> dict[str, Any]:
    current_draft = bundle.current_generated_draft_profile
    public_items = published_item_count(bundle.published_public_profile)
    private_items = published_item_count(bundle.published_private_profile)
    manifest = {
        "current_user_message": {
            "included": bool(bundle.latest_user_message),
            "charCount": len(bundle.latest_user_message),
        },
        "transcript_turns": len(bundle.conversation_transcript_metadata),
        "transcript_context": "metadata_only",
        "generated_items": generated_item_count(current_draft),
        "published_public_items": public_items,
        "published_private_items": max(0, private_items - public_items),
        "archived_items": {
            "count": len(bundle.archived_generated_items_avoidance_context),
            "includedAs": "avoidance_context",
        },
        "rejected_items": {
            "count": len(bundle.archived_generated_items_avoidance_context),
            "includedAs": "avoidance_context",
        },
        "previous_profile_intake_suggestions": {
            "included": bool(bundle.existing_review_queue.get("draftItems")),
            "count": len(bundle.existing_review_queue.get("draftItems") or []),
        },
        "resume_document_text": {
            "included": bool(bundle.resume_document_text),
            "charCount": len(bundle.resume_document_text or ""),
        },
        "approximate_context_char_count": len(bundle.model_dump_json(by_alias=True, exclude={"context_manifest"})),
    }
    return manifest


def generated_item_count(current_draft: dict[str, Any]) -> int:
    if not isinstance(current_draft, dict):
        return 0
    return sum(
        len(current_draft.get(key) or [])
        for key in ("draftFacts", "skillClaims", "experienceAndProjects", "evidenceLinks")
    ) + (1 if current_draft.get("targetRoleIntent") else 0) + len(current_draft.get("profileBasics") or {})


def published_item_count(profile: dict[str, Any]) -> int:
    if not isinstance(profile, dict):
        return 0
    count = sum(len(profile.get(key) or []) for key in ("facts", "skillClaims", "experienceAndProjects", "evidenceLinks"))
    count += 1 if profile.get("targetRoleIntent") else 0
    fields = profile.get("profileFields") if isinstance(profile.get("profileFields"), dict) else {}
    count += sum(len(value or {}) for value in fields.values())
    return count


def recent_transcript_metadata(
    db_session: Session | None,
    intake_session: ProfileIntakeSession | None,
    *,
    limit: int = 6,
) -> list[dict[str, Any]]:
    if db_session is None or intake_session is None:
        return []

    events = list(
        db_session.scalars(
            select(ProfileIntakeEvent)
            .where(ProfileIntakeEvent.session_id == intake_session.id)
            .order_by(ProfileIntakeEvent.created_at.desc())
            .limit(limit)
        )
    )
    return [serialize_transcript_metadata(event) for event in reversed(events)]


def serialize_transcript_metadata(event: ProfileIntakeEvent) -> dict[str, Any]:
    metadata = event.event_metadata if isinstance(event.event_metadata, dict) else {}
    return {
        "role": event.role,
        "eventType": event.event_type,
        "redactedText": event.redacted_text,
        "createdAt": event.created_at.isoformat() if event.created_at is not None else None,
        "metadata": {
            key: value
            for key, value in metadata.items()
            if key
            in {
                "assistantMessageLength",
                "changeSummaryCount",
                "clarifyingQuestionCount",
                "latestUserMessageLength",
                "noChangeReasonPresent",
                "rawTextStored",
                "validationIssueCount",
            }
        },
    }
