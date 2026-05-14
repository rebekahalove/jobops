from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from jobops_api.db.models import (
    CandidateProfile,
    EvidenceArtifact,
    ExperienceProjectDraft,
    ProfileFactDraft,
    ProfileIntakeEvent,
    ProfileIntakeSession,
    RoleTarget,
    SkillClaim,
)

from .artifacts import ProfileIntakeInputMetrics
from .models import ProfileIntakeOutput


def get_or_create_active_intake_session(session: Session, candidate_profile_id: str) -> ProfileIntakeSession:
    intake_session = session.scalar(
        select(ProfileIntakeSession)
        .where(
            ProfileIntakeSession.candidate_profile_id == candidate_profile_id,
            ProfileIntakeSession.status == "active",
        )
        .order_by(ProfileIntakeSession.created_at.desc())
    )
    if intake_session is not None:
        return intake_session

    intake_session = ProfileIntakeSession(
        candidate_profile_id=candidate_profile_id,
        status="active",
        redacted_state={},
    )
    session.add(intake_session)
    session.flush()
    return intake_session


def save_intake_user_event(
    session: Session,
    *,
    intake_session: ProfileIntakeSession,
    candidate_profile_id: str,
    latest_user_message: str,
    artifact_path: str | None,
    model_run_id: str | None = None,
) -> ProfileIntakeEvent:
    event = ProfileIntakeEvent(
        session_id=intake_session.id,
        candidate_profile_id=candidate_profile_id,
        role="user",
        event_type="message",
        redacted_text=None,
        raw_text_artifact_path=artifact_path,
        model_run_id=model_run_id,
        event_metadata={
            "latestUserMessageLength": len(latest_user_message),
            "rawTextStored": False,
        },
    )
    session.add(event)
    return event


def save_intake_assistant_event(
    session: Session,
    *,
    intake_session: ProfileIntakeSession,
    candidate_profile_id: str,
    output: ProfileIntakeOutput,
    artifact_path: str | None,
    model_run_id: str | None,
) -> ProfileIntakeEvent:
    event = ProfileIntakeEvent(
        session_id=intake_session.id,
        candidate_profile_id=candidate_profile_id,
        role="assistant",
        event_type="model_result",
        redacted_text=None,
        raw_text_artifact_path=artifact_path,
        model_run_id=model_run_id,
        event_metadata={
            "assistantMessageLength": len(output.assistant_message),
            "changeSummaryCount": len(output.change_summary),
            "clarifyingQuestionCount": len(output.clarifying_questions),
            **draft_count_metadata(output),
        },
    )
    session.add(event)
    return event


def save_intake_validation_error_event(
    session: Session,
    *,
    intake_session: ProfileIntakeSession,
    candidate_profile_id: str,
    issues: list[str],
    artifact_path: str | None,
    model_run_id: str | None,
) -> ProfileIntakeEvent:
    event = ProfileIntakeEvent(
        session_id=intake_session.id,
        candidate_profile_id=candidate_profile_id,
        role="system",
        event_type="validation_error",
        redacted_text=None,
        raw_text_artifact_path=artifact_path,
        model_run_id=model_run_id,
        event_metadata={
            "validationIssueCount": len(issues),
            "issues": issues[:8],
        },
    )
    session.add(event)
    return event


def persist_profile_intake_output(
    session: Session,
    *,
    candidate_profile: CandidateProfile,
    intake_session: ProfileIntakeSession,
    output: ProfileIntakeOutput,
    input_metrics: ProfileIntakeInputMetrics,
    artifact_path: str | None,
    model_run_id: str | None,
) -> dict[str, Any]:
    replace_current_session_drafts(session, intake_session.id)

    saved_role_target = save_role_target(session, candidate_profile, intake_session, output)
    saved_facts = save_draft_facts(session, candidate_profile, intake_session, output)
    saved_skills = save_skill_claims(session, candidate_profile, intake_session, output)
    saved_experiences = save_experience_projects(session, candidate_profile, intake_session, output)
    saved_evidence = save_evidence_links(session, candidate_profile, intake_session, output)

    saved_snapshot = build_saved_profile_draft_snapshot(
        output=output,
        role_target=saved_role_target,
        facts=saved_facts,
        skills=saved_skills,
        experiences=saved_experiences,
        evidence=saved_evidence,
    )

    intake_session.last_turn_at = datetime.now(timezone.utc)
    intake_session.target_role_summary = role_target_summary(output)
    intake_session.redacted_state = {
        "artifactPath": artifact_path,
        "draftCounts": draft_count_metadata(output),
        "input": input_metrics.to_json(),
        "lastChangeSummaryCount": len(output.change_summary),
        "lastClarifyingQuestionCount": len(output.clarifying_questions),
        "latestDraftSnapshot": saved_snapshot,
        "modelRunId": model_run_id,
    }

    session.flush()
    return saved_snapshot


def get_latest_profile_draft_snapshot(session: Session, candidate_profile: CandidateProfile) -> dict[str, Any]:
    intake_session = session.scalar(
        select(ProfileIntakeSession)
        .where(ProfileIntakeSession.candidate_profile_id == candidate_profile.id)
        .order_by(ProfileIntakeSession.last_turn_at.desc().nullslast(), ProfileIntakeSession.created_at.desc())
    )

    if intake_session is None:
        return empty_profile_draft_snapshot()

    redacted_state = intake_session.redacted_state if isinstance(intake_session.redacted_state, dict) else {}
    latest_snapshot = redacted_state.get("latestDraftSnapshot")
    if isinstance(latest_snapshot, dict):
        return {
            **empty_profile_draft_snapshot(),
            **latest_snapshot,
            "statusSummary": build_intake_status_summary(intake_session, redacted_state),
        }

    return {
        **build_profile_draft_snapshot_from_rows(session, intake_session),
        "statusSummary": build_intake_status_summary(intake_session, redacted_state),
    }


def build_profile_draft_snapshot_from_rows(session: Session, intake_session: ProfileIntakeSession) -> dict[str, Any]:
    role_target = session.scalar(
        select(RoleTarget)
        .where(RoleTarget.profile_intake_session_id == intake_session.id, RoleTarget.is_active.is_(True))
        .order_by(RoleTarget.updated_at.desc())
    )
    facts = session.scalars(
        select(ProfileFactDraft)
        .where(ProfileFactDraft.profile_intake_session_id == intake_session.id)
        .order_by(ProfileFactDraft.created_at.asc())
    ).all()
    skills = session.scalars(
        select(SkillClaim)
        .where(SkillClaim.profile_intake_session_id == intake_session.id)
        .order_by(SkillClaim.created_at.asc())
    ).all()
    experiences = session.scalars(
        select(ExperienceProjectDraft)
        .where(ExperienceProjectDraft.profile_intake_session_id == intake_session.id)
        .order_by(ExperienceProjectDraft.created_at.asc())
    ).all()
    evidence = session.scalars(
        select(EvidenceArtifact)
        .where(EvidenceArtifact.profile_intake_session_id == intake_session.id)
        .order_by(EvidenceArtifact.created_at.asc())
    ).all()

    return {
        "assistantMessage": "",
        "targetRoleIntent": serialize_role_target_from_row(role_target),
        "draftFacts": [
            {
                "id": fact.id,
                "claim": fact.claim,
                "category": fact.fact_type,
                "source": normalize_source(fact.source),
                "status": "needs_review",
                "visibility": "private",
                "published": False,
            }
            for fact in facts
        ],
        "skillClaims": [
            {
                "id": skill.id,
                "skill": skill.skill_name,
                "category": skill.skill_category,
                "evidence": skill.evidence_summary,
                "source": normalize_source(skill.source),
                "status": "draft",
                "visibility": "private",
                "published": False,
            }
            for skill in skills
        ],
        "experienceAndProjects": [
            {
                "id": item.id,
                "title": item.title,
                "organization": item.organization,
                "summary": item.summary,
                "source": normalize_source(item.source),
                "status": "needs_review",
                "visibility": "private",
                "published": False,
            }
            for item in experiences
        ],
        "evidenceLinks": [
            {
                "id": item.id,
                "url": item.uri or "",
                "label": item.label,
                "source": normalize_source(item.source),
                "status": "needs_review",
                "visibility": "private",
                "published": False,
            }
            for item in evidence
        ],
        "clarifyingQuestions": [],
        "changeSummary": [],
    }


def empty_profile_draft_snapshot() -> dict[str, Any]:
    return {
        "assistantMessage": "",
        "targetRoleIntent": {},
        "draftFacts": [],
        "skillClaims": [],
        "experienceAndProjects": [],
        "evidenceLinks": [],
        "clarifyingQuestions": [],
        "changeSummary": [],
        "statusSummary": "No profile intake draft has been saved yet.",
    }


def build_intake_status_summary(intake_session: ProfileIntakeSession, redacted_state: dict[str, Any]) -> str:
    counts = redacted_state.get("draftCounts") if isinstance(redacted_state.get("draftCounts"), dict) else {}
    fact_count = counts.get("draftFactCount", 0)
    skill_count = counts.get("skillClaimCount", 0)
    experience_count = counts.get("experienceAndProjectCount", 0)
    if intake_session.last_turn_at is None:
        return "Profile intake session is active, but no completed turn has been saved yet."
    return (
        f"Latest saved intake turn created {fact_count} draft fact(s), {skill_count} skill claim(s), "
        f"and {experience_count} experience/project item(s)."
    )


def serialize_role_target_from_row(role_target: RoleTarget | None) -> dict[str, Any]:
    if role_target is None:
        return {}

    constraints = role_target.constraints if isinstance(role_target.constraints, dict) else {}
    payload = {
        "targetTitles": join_text_list(role_target.target_titles),
        "targetRoleFamilies": join_text_list(role_target.role_families),
        "preferredWorkMode": role_target.work_modes[0] if role_target.work_modes else None,
        "preferredLocations": join_text_list(role_target.preferred_locations),
        "domainsOrIndustries": constraints.get("domainsOrIndustries"),
        "constraints": constraints.get("constraints"),
    }
    return {key: value for key, value in payload.items() if value}


def replace_current_session_drafts(session: Session, intake_session_id: str) -> None:
    for model in (RoleTarget, ProfileFactDraft, SkillClaim, ExperienceProjectDraft, EvidenceArtifact):
        session.execute(delete(model).where(model.profile_intake_session_id == intake_session_id))


def save_role_target(
    session: Session,
    candidate_profile: CandidateProfile,
    intake_session: ProfileIntakeSession,
    output: ProfileIntakeOutput,
) -> RoleTarget | None:
    intent = output.target_role_intent
    if not any(
        [
            intent.target_titles,
            intent.target_role_families,
            intent.preferred_work_mode,
            intent.preferred_locations,
            intent.domains_or_industries,
            intent.constraints,
        ]
    ):
        return None

    role_target = RoleTarget(
        candidate_profile_id=candidate_profile.id,
        profile_intake_session_id=intake_session.id,
        target_titles=split_text_list(intent.target_titles),
        role_families=split_text_list(intent.target_role_families),
        preferred_locations=split_text_list(intent.preferred_locations),
        work_modes=[intent.preferred_work_mode] if intent.preferred_work_mode else [],
        constraints={
            "domainsOrIndustries": intent.domains_or_industries,
            "constraints": intent.constraints,
        },
        source="model",
        review_status="needs_review",
        visibility="private",
        publication_status="not_published",
        is_active=True,
    )
    session.add(role_target)
    return role_target


def save_draft_facts(
    session: Session,
    candidate_profile: CandidateProfile,
    intake_session: ProfileIntakeSession,
    output: ProfileIntakeOutput,
) -> list[ProfileFactDraft]:
    saved: list[ProfileFactDraft] = []
    for fact in output.draft_facts:
        row = ProfileFactDraft(
            candidate_profile_id=candidate_profile.id,
            profile_intake_session_id=intake_session.id,
            claim=fact.claim,
            fact_type=fact.category or "general",
            structured_value={
                "published": False,
                "sourceStatus": fact.status,
            },
            source=fact.source,
            confidence="unknown",
            suggested_visibility="private",
            review_status="needs_review",
        )
        session.add(row)
        saved.append(row)
    return saved


def save_skill_claims(
    session: Session,
    candidate_profile: CandidateProfile,
    intake_session: ProfileIntakeSession,
    output: ProfileIntakeOutput,
) -> list[SkillClaim]:
    saved: list[SkillClaim] = []
    for skill in output.skill_claims:
        row = SkillClaim(
            candidate_profile_id=candidate_profile.id,
            profile_intake_session_id=intake_session.id,
            skill_name=skill.skill,
            skill_category=skill.category or "general",
            evidence_summary=skill.evidence,
            evidence_fact_ids=[],
            source=skill.source,
            visibility="private",
            verification_status="draft",
            publication_status="not_published",
        )
        session.add(row)
        saved.append(row)
    return saved


def save_experience_projects(
    session: Session,
    candidate_profile: CandidateProfile,
    intake_session: ProfileIntakeSession,
    output: ProfileIntakeOutput,
) -> list[ExperienceProjectDraft]:
    saved: list[ExperienceProjectDraft] = []
    for item in output.experience_and_projects:
        row = ExperienceProjectDraft(
            candidate_profile_id=candidate_profile.id,
            profile_intake_session_id=intake_session.id,
            title=item.title,
            organization=item.organization,
            summary=item.summary,
            source=item.source,
            visibility="private",
            review_status="needs_review",
            publication_status="not_published",
            structured_value={
                "published": False,
                "sourceStatus": item.status,
            },
        )
        session.add(row)
        saved.append(row)
    return saved


def save_evidence_links(
    session: Session,
    candidate_profile: CandidateProfile,
    intake_session: ProfileIntakeSession,
    output: ProfileIntakeOutput,
) -> list[EvidenceArtifact]:
    saved: list[EvidenceArtifact] = []
    for link in output.evidence_links:
        row = EvidenceArtifact(
            candidate_profile_id=candidate_profile.id,
            profile_intake_session_id=intake_session.id,
            artifact_type="link",
            label=link.label or link.url,
            uri=link.url,
            source=link.source,
            visibility="private",
            review_status="needs_review",
            publication_status="not_published",
            artifact_metadata={
                "published": False,
                "sourceStatus": link.status,
            },
        )
        session.add(row)
        saved.append(row)
    return saved


def build_saved_profile_draft_snapshot(
    *,
    output: ProfileIntakeOutput,
    role_target: RoleTarget | None,
    facts: list[ProfileFactDraft],
    skills: list[SkillClaim],
    experiences: list[ExperienceProjectDraft],
    evidence: list[EvidenceArtifact],
) -> dict[str, Any]:
    return {
        "assistantMessage": output.assistant_message,
        "targetRoleIntent": serialize_role_target(role_target, output),
        "draftFacts": [
            {
                "id": fact.id,
                "claim": fact.claim,
                "category": fact.fact_type,
                "source": normalize_source(fact.source),
                "status": "needs_review",
                "visibility": "private",
                "published": False,
            }
            for fact in facts
        ],
        "skillClaims": [
            {
                "id": skill.id,
                "skill": skill.skill_name,
                "category": skill.skill_category,
                "evidence": skill.evidence_summary,
                "source": normalize_source(skill.source),
                "status": "draft",
                "visibility": "private",
                "published": False,
            }
            for skill in skills
        ],
        "experienceAndProjects": [
            {
                "id": item.id,
                "title": item.title,
                "organization": item.organization,
                "summary": item.summary,
                "source": normalize_source(item.source),
                "status": "needs_review",
                "visibility": "private",
                "published": False,
            }
            for item in experiences
        ],
        "evidenceLinks": [
            {
                "id": item.id,
                "url": item.uri or "",
                "label": item.label,
                "source": normalize_source(item.source),
                "status": "needs_review",
                "visibility": "private",
                "published": False,
            }
            for item in evidence
        ],
        "clarifyingQuestions": output.clarifying_questions,
        "changeSummary": output.change_summary,
    }


def serialize_role_target(role_target: RoleTarget | None, output: ProfileIntakeOutput) -> dict[str, Any]:
    if role_target is None:
        return output.target_role_intent.model_dump(by_alias=True, exclude_none=True)

    constraints = role_target.constraints if isinstance(role_target.constraints, dict) else {}
    payload = {
        "targetTitles": join_text_list(role_target.target_titles),
        "targetRoleFamilies": join_text_list(role_target.role_families),
        "preferredWorkMode": role_target.work_modes[0] if role_target.work_modes else None,
        "preferredLocations": join_text_list(role_target.preferred_locations),
        "domainsOrIndustries": constraints.get("domainsOrIndustries"),
        "constraints": constraints.get("constraints"),
    }
    return {key: value for key, value in payload.items() if value}


def role_target_summary(output: ProfileIntakeOutput) -> str:
    intent = output.target_role_intent
    values = [
        intent.target_titles,
        intent.target_role_families,
        intent.preferred_work_mode,
        intent.preferred_locations,
        intent.domains_or_industries,
        intent.constraints,
    ]
    return " | ".join(value for value in values if value)


def split_text_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.replace("|", ",").replace(";", ",").split(",") if part.strip()]


def join_text_list(value: list[str] | None) -> str | None:
    if not value:
        return None
    return ", ".join(value)


def normalize_source(value: str | None) -> str:
    return value if value in {"chat", "resume", "model"} else "model"


def draft_count_metadata(output: ProfileIntakeOutput) -> dict[str, int]:
    return {
        "draftFactCount": len(output.draft_facts),
        "skillClaimCount": len(output.skill_claims),
        "experienceAndProjectCount": len(output.experience_and_projects),
        "evidenceLinkCount": len(output.evidence_links),
    }
