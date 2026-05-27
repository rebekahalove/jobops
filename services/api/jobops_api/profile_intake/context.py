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
    conversation_transcript: list[dict[str, Any]] = Field(default_factory=list, alias="conversationTranscript")
    current_generated_draft_profile: dict[str, Any] = Field(default_factory=dict, alias="currentGeneratedDraftProfile")
    published_private_profile: dict[str, Any] = Field(default_factory=dict, alias="publishedPrivateProfile")
    published_public_profile: dict[str, Any] = Field(default_factory=dict, alias="publishedPublicProfile")
    existing_review_queue: dict[str, Any] = Field(default_factory=dict, alias="existingReviewQueue")
    resume_document_text: str | None = Field(default=None, alias="resumeDocumentText")
    profile_targets_and_basics: dict[str, Any] = Field(default_factory=dict, alias="profileTargetsAndBasics")
    client_existing_draft: dict[str, Any] | None = Field(default=None, alias="clientExistingDraft")
    authoritative_current_draft_source: str = Field(default="database", alias="authoritativeCurrentDraftSource")


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

    return ProfileIntakeContextBundle(
        latestUserMessage=request.latest_user_message,
        conversationTranscript=recent_transcript_events(db_session, intake_session),
        currentGeneratedDraftProfile=current_draft,
        publishedPrivateProfile=published_profile,
        publishedPublicProfile=public_profile,
        existingReviewQueue={
            "draftItems": private_context.get("draft_items") or [],
            "archivedSuppressedItemsSummary": (private_context.get("archived_suppressed_items_summary") or [])[:10],
        },
        resumeDocumentText=None,
        profileTargetsAndBasics={
            "profileBasics": current_draft.get("profileBasics") if isinstance(current_draft.get("profileBasics"), dict) else {},
            "targetRoleIntent": (
                current_draft.get("targetRoleIntent") if isinstance(current_draft.get("targetRoleIntent"), dict) else {}
            ),
        },
        clientExistingDraft=request.existing_draft,
        authoritativeCurrentDraftSource=authoritative_current_draft_source,
    )


def recent_transcript_events(
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
    return [serialize_transcript_event(event) for event in reversed(events)]


def serialize_transcript_event(event: ProfileIntakeEvent) -> dict[str, Any]:
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
