from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from jobops_api.db.models import (
    CandidateProfile,
    EvidenceArtifact,
    ExperienceProjectDraft,
    ProfileFact,
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


def ensure_editable_profile_intake_draft(
    session: Session,
    *,
    candidate_profile: CandidateProfile,
    intake_session: ProfileIntakeSession,
) -> bool:
    """Seed a private draft from published profile rows without editing published rows."""
    if has_profile_intake_draft_rows(session, intake_session.id) or has_saved_draft_snapshot(intake_session):
        return False

    seeded_any = False
    published_role_target = get_latest_published_role_target(session, candidate_profile.id)
    if published_role_target is not None:
        session.add(
            RoleTarget(
                candidate_profile_id=candidate_profile.id,
                profile_intake_session_id=intake_session.id,
                target_titles=list(published_role_target.target_titles or []),
                role_families=list(published_role_target.role_families or []),
                seniority=published_role_target.seniority,
                preferred_locations=list(published_role_target.preferred_locations or []),
                work_modes=list(published_role_target.work_modes or []),
                constraints=dict(published_role_target.constraints or {}),
                source=published_role_target.source,
                review_status="needs_review",
                visibility="private",
                publication_status="not_published",
                is_active=True,
            )
        )
        seeded_any = True

    for fact in get_published_profile_facts(session, candidate_profile.id):
        session.add(
            ProfileFactDraft(
                candidate_profile_id=candidate_profile.id,
                profile_intake_session_id=intake_session.id,
                claim=fact.claim,
                fact_type=fact.fact_type,
                structured_value={
                    "derivedFromPublishedFactId": fact.id,
                    "published": False,
                    "sourceStatus": "needs_review",
                },
                source=fact.source,
                confidence="unknown",
                suggested_visibility="private",
                review_status="needs_review",
            )
        )
        seeded_any = True

    if seeded_any:
        session.flush()

    return seeded_any


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
            "noChangeReasonPresent": bool(output.no_change_reason),
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
    saved_role_target = sync_role_target(session, candidate_profile, intake_session, output)
    saved_facts = sync_draft_facts(session, candidate_profile, intake_session, output)
    saved_skills = sync_skill_claims(session, candidate_profile, intake_session, output)
    saved_experiences = sync_experience_projects(session, candidate_profile, intake_session, output)
    saved_evidence = sync_evidence_links(session, candidate_profile, intake_session, output)
    session.flush()

    saved_snapshot = build_saved_profile_draft_snapshot(
        output=output,
        role_target=saved_role_target,
        facts=saved_facts,
        skills=saved_skills,
        experiences=saved_experiences,
        evidence=saved_evidence,
    )
    draft_counts = draft_count_metadata_from_saved(
        facts=saved_facts,
        skills=saved_skills,
        experiences=saved_experiences,
        evidence=saved_evidence,
    )

    intake_session.last_turn_at = datetime.now(timezone.utc)
    intake_session.target_role_summary = role_target_summary_from_row(saved_role_target) or intake_session.target_role_summary
    intake_session.redacted_state = {
        "artifactPath": artifact_path,
        "draftCounts": draft_counts,
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

    return get_profile_draft_snapshot_for_session(session, intake_session)


def get_profile_draft_snapshot_for_session(session: Session, intake_session: ProfileIntakeSession) -> dict[str, Any]:
    redacted_state = intake_session.redacted_state if isinstance(intake_session.redacted_state, dict) else {}
    latest_snapshot = redacted_state.get("latestDraftSnapshot")
    if isinstance(latest_snapshot, dict) and not has_profile_intake_draft_rows(session, intake_session.id):
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
    role_target = get_active_role_target(session, intake_session.id)
    facts = get_session_facts(session, intake_session.id)
    skills = get_session_skills(session, intake_session.id)
    experiences = get_session_experiences(session, intake_session.id)
    evidence = get_session_evidence(session, intake_session.id)

    return {
        "assistantMessage": "",
        "targetRoleIntent": serialize_role_target_from_row(role_target),
        "draftFacts": [serialize_fact_draft(fact) for fact in facts],
        "skillClaims": [serialize_skill_claim(skill) for skill in skills],
        "experienceAndProjects": [serialize_experience_project(item) for item in experiences],
        "evidenceLinks": [serialize_evidence_link(item) for item in evidence],
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
        f"Latest saved intake turn left the draft with {fact_count} draft fact(s), {skill_count} skill claim(s), "
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
        "preferredLocations": join_location_list(role_target.preferred_locations),
        "domainsOrIndustries": constraints.get("domainsOrIndustries"),
        "constraints": constraints.get("constraints"),
    }
    return {key: value for key, value in payload.items() if value}


def has_profile_intake_draft_rows(session: Session, intake_session_id: str) -> bool:
    return any(
        session.scalar(select(model.id).where(model.profile_intake_session_id == intake_session_id).limit(1))
        is not None
        for model in (RoleTarget, ProfileFactDraft, SkillClaim, ExperienceProjectDraft, EvidenceArtifact)
    )


def has_saved_draft_snapshot(intake_session: ProfileIntakeSession) -> bool:
    redacted_state = intake_session.redacted_state if isinstance(intake_session.redacted_state, dict) else {}
    snapshot = redacted_state.get("latestDraftSnapshot")
    if not isinstance(snapshot, dict):
        return False
    target_role_intent = snapshot.get("targetRoleIntent")
    return bool(
        (isinstance(target_role_intent, dict) and any(target_role_intent.values()))
        or snapshot.get("draftFacts")
        or snapshot.get("skillClaims")
        or snapshot.get("experienceAndProjects")
        or snapshot.get("evidenceLinks")
    )


def get_latest_published_role_target(session: Session, candidate_profile_id: str) -> RoleTarget | None:
    return session.scalar(
        select(RoleTarget)
        .where(
            RoleTarget.candidate_profile_id == candidate_profile_id,
            RoleTarget.publication_status == "published",
            RoleTarget.is_active.is_(True),
        )
        .order_by(RoleTarget.updated_at.desc(), RoleTarget.created_at.desc())
    )


def get_published_profile_facts(session: Session, candidate_profile_id: str) -> list[ProfileFact]:
    return list(
        session.scalars(
            select(ProfileFact)
            .where(
                ProfileFact.candidate_profile_id == candidate_profile_id,
                ProfileFact.visibility == "public",
                ProfileFact.verification_status == "published",
            )
            .order_by(ProfileFact.created_at.asc())
        )
    )


def replace_current_session_drafts(session: Session, intake_session_id: str) -> None:
    for model in (RoleTarget, ProfileFactDraft, SkillClaim, ExperienceProjectDraft, EvidenceArtifact):
        session.execute(delete(model).where(model.profile_intake_session_id == intake_session_id))


def sync_role_target(
    session: Session,
    candidate_profile: CandidateProfile,
    intake_session: ProfileIntakeSession,
    output: ProfileIntakeOutput,
) -> RoleTarget | None:
    intent = output.updated_draft_profile.target_role_intent
    existing = get_active_role_target(session, intake_session.id)

    if existing is not None and existing.publication_status == "published":
        return existing

    removed_fields = set(output.removed_items.target_role_intent_fields)
    target_titles = split_text_list(intent.target_titles)
    role_families = split_text_list(intent.target_role_families)
    preferred_locations = split_location_text_list(intent.preferred_locations)
    work_modes = [intent.preferred_work_mode] if meaningful_text(intent.preferred_work_mode) else []
    domains_or_industries = meaningful_text(intent.domains_or_industries)
    constraints_text = meaningful_text(intent.constraints)

    if existing is None:
        if not any([target_titles, role_families, work_modes, preferred_locations, domains_or_industries, constraints_text]):
            return None
        role_target = RoleTarget(
            candidate_profile_id=candidate_profile.id,
            profile_intake_session_id=intake_session.id,
            target_titles=target_titles,
            role_families=role_families,
            preferred_locations=preferred_locations,
            work_modes=work_modes,
            constraints={
                **({"domainsOrIndustries": domains_or_industries} if domains_or_industries else {}),
                **({"constraints": constraints_text} if constraints_text else {}),
            },
            source="model",
            review_status="needs_review",
            visibility="private",
            publication_status="not_published",
            is_active=True,
        )
        session.add(role_target)
        return role_target

    if target_titles or "targetRoleIntent.targetTitles" in removed_fields:
        existing.target_titles = target_titles
    if role_families or "targetRoleIntent.targetRoleFamilies" in removed_fields:
        existing.role_families = role_families
    if preferred_locations or "targetRoleIntent.preferredLocations" in removed_fields:
        existing.preferred_locations = preferred_locations
    if work_modes or "targetRoleIntent.preferredWorkMode" in removed_fields:
        existing.work_modes = work_modes

    constraints = existing.constraints if isinstance(existing.constraints, dict) else {}
    if domains_or_industries or "targetRoleIntent.domainsOrIndustries" in removed_fields:
        constraints = {**constraints, "domainsOrIndustries": domains_or_industries}
    if constraints_text or "targetRoleIntent.constraints" in removed_fields:
        constraints = {**constraints, "constraints": constraints_text}
    existing.constraints = {key: value for key, value in constraints.items() if value}
    return existing


def sync_draft_facts(
    session: Session,
    candidate_profile: CandidateProfile,
    intake_session: ProfileIntakeSession,
    output: ProfileIntakeOutput,
) -> list[ProfileFactDraft]:
    saved = get_session_facts(session, intake_session.id)
    existing_by_id = {row.id: row for row in saved}
    existing_by_key = {fact_key(row.claim, row.fact_type): row for row in saved}
    returned_ids: set[str] = set()

    for fact in output.updated_draft_profile.draft_facts:
        claim = meaningful_text(fact.claim)
        if not claim:
            continue
        category = meaningful_text(fact.category) or "general"
        existing = existing_by_id.get(fact.id) if fact.id else None
        if existing is not None:
            returned_ids.add(existing.id)
            if not draft_fact_is_published(existing):
                existing.claim = claim
                existing.fact_type = category
                existing.source = fact.source
            continue

        key = fact_key(claim, category)
        if key in existing_by_key:
            returned_ids.add(existing_by_key[key].id)
            continue
        row = ProfileFactDraft(
            candidate_profile_id=candidate_profile.id,
            profile_intake_session_id=intake_session.id,
            claim=claim,
            fact_type=category,
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
        session.flush()
        returned_ids.add(row.id)
        existing_by_key[key] = row

    remove_ids = set(output.removed_items.draft_fact_ids)
    for row in saved:
        if row.id in returned_ids:
            continue
        if row.id in remove_ids and not draft_fact_is_published(row):
            session.delete(row)

    session.flush()
    return get_session_facts(session, intake_session.id)


def sync_skill_claims(
    session: Session,
    candidate_profile: CandidateProfile,
    intake_session: ProfileIntakeSession,
    output: ProfileIntakeOutput,
) -> list[SkillClaim]:
    saved = get_session_skills(session, intake_session.id)
    existing_by_id = {row.id: row for row in saved}
    existing_by_key = {skill_key(row.skill_name, row.skill_category): row for row in saved}
    returned_ids: set[str] = set()

    for skill in output.updated_draft_profile.skill_claims:
        skill_name = meaningful_text(skill.skill)
        if not skill_name:
            continue
        category = meaningful_text(skill.category) or "general"
        evidence = meaningful_text(skill.evidence)
        existing = existing_by_id.get(skill.id) if skill.id else None
        if existing is not None:
            returned_ids.add(existing.id)
            if existing.publication_status != "published":
                existing.skill_name = skill_name
                existing.skill_category = category
                existing.evidence_summary = evidence
                existing.years_min = skill.years_min
                existing.years_max = skill.years_max
                existing.source = skill.source
            continue

        key = skill_key(skill_name, category)
        if key in existing_by_key:
            returned_ids.add(existing_by_key[key].id)
            continue
        row = SkillClaim(
            candidate_profile_id=candidate_profile.id,
            profile_intake_session_id=intake_session.id,
            skill_name=skill_name,
            skill_category=category,
            years_min=skill.years_min,
            years_max=skill.years_max,
            evidence_summary=evidence,
            evidence_fact_ids=[],
            source=skill.source,
            visibility="private",
            verification_status="draft",
            publication_status="not_published",
        )
        session.add(row)
        session.flush()
        returned_ids.add(row.id)
        existing_by_key[key] = row

    remove_ids = set(output.removed_items.skill_claim_ids)
    for row in saved:
        if row.id in returned_ids:
            continue
        if row.id in remove_ids and row.publication_status != "published":
            session.delete(row)

    session.flush()
    return get_session_skills(session, intake_session.id)


def sync_experience_projects(
    session: Session,
    candidate_profile: CandidateProfile,
    intake_session: ProfileIntakeSession,
    output: ProfileIntakeOutput,
) -> list[ExperienceProjectDraft]:
    saved = get_session_experiences(session, intake_session.id)
    existing_by_id = {row.id: row for row in saved}
    exact_by_key, title_by_key = experience_indexes(saved)
    returned_ids: set[str] = set()

    for item in output.updated_draft_profile.experience_and_projects:
        title = meaningful_text(item.title)
        if not title:
            continue
        organization = meaningful_text(item.organization)
        summary = meaningful_text(item.summary) or ""
        existing = existing_by_id.get(item.id) if item.id else None
        if existing is not None:
            returned_ids.add(existing.id)
            if existing.publication_status != "published":
                existing.title = title
                existing.organization = organization
                existing.summary = summary
                apply_experience_fields(existing, item)
                existing.structured_value = experience_structured_value(item)
                existing.source = item.source
            continue

        existing = exact_by_key.get(experience_key(title, organization)) or title_by_key.get(normalize_key(title))
        if existing is not None:
            returned_ids.add(existing.id)
            if existing.publication_status != "published":
                existing.title = title
                if organization:
                    existing.organization = organization
                if summary:
                    existing.summary = summary
                apply_experience_fields(existing, item)
                existing.structured_value = experience_structured_value(item)
                existing.source = item.source
            continue
        row = ExperienceProjectDraft(
            candidate_profile_id=candidate_profile.id,
            profile_intake_session_id=intake_session.id,
            title=title,
            organization=organization,
            start_date=meaningful_text(item.start_date),
            end_date=meaningful_text(item.end_date),
            location=meaningful_text(item.location),
            summary=summary,
            source=item.source,
            visibility="private",
            review_status="needs_review",
            publication_status="not_published",
            structured_value={
                **experience_structured_value(item),
            },
        )
        session.add(row)
        session.flush()
        returned_ids.add(row.id)
        saved.append(row)
        exact_by_key[experience_key(title, organization)] = row
        title_by_key = rebuild_unique_title_index(saved)

    remove_ids = set(output.removed_items.experience_and_project_ids)
    for row in saved:
        if row.id in returned_ids:
            continue
        if row.id in remove_ids and row.publication_status != "published":
            session.delete(row)

    session.flush()
    return get_session_experiences(session, intake_session.id)


def sync_evidence_links(
    session: Session,
    candidate_profile: CandidateProfile,
    intake_session: ProfileIntakeSession,
    output: ProfileIntakeOutput,
) -> list[EvidenceArtifact]:
    saved = get_session_evidence(session, intake_session.id)
    existing_by_id = {row.id: row for row in saved}
    existing_by_key = {evidence_key(row.uri, row.label): row for row in saved}
    returned_ids: set[str] = set()

    for link in output.updated_draft_profile.evidence_links:
        url = meaningful_text(link.url)
        label = meaningful_text(link.label)
        if not url and not label:
            continue
        existing = existing_by_id.get(link.id) if link.id else None
        if existing is not None:
            returned_ids.add(existing.id)
            if existing.publication_status != "published":
                existing.uri = url
                existing.label = label or url or "Evidence link"
                existing.source = link.source
            continue

        key = evidence_key(url, label)
        if key in existing_by_key:
            returned_ids.add(existing_by_key[key].id)
            continue
        row = EvidenceArtifact(
            candidate_profile_id=candidate_profile.id,
            profile_intake_session_id=intake_session.id,
            artifact_type="link",
            label=label or url or "Evidence link",
            uri=url,
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
        session.flush()
        returned_ids.add(row.id)
        existing_by_key[key] = row

    remove_ids = set(output.removed_items.evidence_link_ids)
    for row in saved:
        if row.id in returned_ids:
            continue
        if row.id in remove_ids and row.publication_status != "published":
            session.delete(row)

    session.flush()
    return get_session_evidence(session, intake_session.id)


def draft_fact_is_published(row: ProfileFactDraft) -> bool:
    structured_value = row.structured_value if isinstance(row.structured_value, dict) else {}
    return bool(structured_value.get("published"))


def merge_role_target(
    session: Session,
    candidate_profile: CandidateProfile,
    intake_session: ProfileIntakeSession,
    output: ProfileIntakeOutput,
) -> RoleTarget | None:
    intent = output.updated_draft_profile.target_role_intent
    existing = get_active_role_target(session, intake_session.id)
    target_titles = split_text_list(intent.target_titles)
    role_families = split_text_list(intent.target_role_families)
    preferred_locations = split_location_text_list(intent.preferred_locations)
    work_modes = [intent.preferred_work_mode] if meaningful_text(intent.preferred_work_mode) else []
    domains_or_industries = meaningful_text(intent.domains_or_industries)
    constraints_text = meaningful_text(intent.constraints)

    if not any([target_titles, role_families, work_modes, preferred_locations, domains_or_industries, constraints_text]):
        return existing

    if existing is not None:
        if target_titles:
            existing.target_titles = target_titles
        if role_families:
            existing.role_families = role_families
        if preferred_locations:
            existing.preferred_locations = preferred_locations
        if work_modes:
            existing.work_modes = work_modes
        constraints = existing.constraints if isinstance(existing.constraints, dict) else {}
        if domains_or_industries:
            constraints = {**constraints, "domainsOrIndustries": domains_or_industries}
        if constraints_text:
            constraints = {**constraints, "constraints": constraints_text}
        existing.constraints = constraints
        return existing

    role_target = RoleTarget(
        candidate_profile_id=candidate_profile.id,
        profile_intake_session_id=intake_session.id,
        target_titles=target_titles,
        role_families=role_families,
        preferred_locations=preferred_locations,
        work_modes=work_modes,
        constraints={
            **({"domainsOrIndustries": domains_or_industries} if domains_or_industries else {}),
            **({"constraints": constraints_text} if constraints_text else {}),
        },
        source="model",
        review_status="needs_review",
        visibility="private",
        publication_status="not_published",
        is_active=True,
    )
    session.add(role_target)
    return role_target


def merge_draft_facts(
    session: Session,
    candidate_profile: CandidateProfile,
    intake_session: ProfileIntakeSession,
    output: ProfileIntakeOutput,
) -> list[ProfileFactDraft]:
    saved = get_session_facts(session, intake_session.id)
    existing_by_key = {fact_key(row.claim, row.fact_type): row for row in saved}
    for fact in output.updated_draft_profile.draft_facts:
        claim = meaningful_text(fact.claim)
        if not claim:
            continue
        category = meaningful_text(fact.category) or "general"
        key = fact_key(claim, category)
        if key in existing_by_key:
            continue
        row = ProfileFactDraft(
            candidate_profile_id=candidate_profile.id,
            profile_intake_session_id=intake_session.id,
            claim=claim,
            fact_type=category,
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
        existing_by_key[key] = row
    return saved


def merge_skill_claims(
    session: Session,
    candidate_profile: CandidateProfile,
    intake_session: ProfileIntakeSession,
    output: ProfileIntakeOutput,
) -> list[SkillClaim]:
    saved = get_session_skills(session, intake_session.id)
    existing_by_key = {skill_key(row.skill_name, row.skill_category): row for row in saved}
    for skill in output.updated_draft_profile.skill_claims:
        skill_name = meaningful_text(skill.skill)
        if not skill_name:
            continue
        category = meaningful_text(skill.category) or "general"
        evidence = meaningful_text(skill.evidence)
        key = skill_key(skill_name, category)
        existing = existing_by_key.get(key)
        if existing is not None:
            if not meaningful_text(existing.evidence_summary) and evidence:
                existing.evidence_summary = evidence
            continue
        row = SkillClaim(
            candidate_profile_id=candidate_profile.id,
            profile_intake_session_id=intake_session.id,
            skill_name=skill_name,
            skill_category=category,
            evidence_summary=evidence,
            evidence_fact_ids=[],
            source=skill.source,
            visibility="private",
            verification_status="draft",
            publication_status="not_published",
        )
        session.add(row)
        saved.append(row)
        existing_by_key[key] = row
    return saved


def merge_experience_projects(
    session: Session,
    candidate_profile: CandidateProfile,
    intake_session: ProfileIntakeSession,
    output: ProfileIntakeOutput,
) -> list[ExperienceProjectDraft]:
    saved = get_session_experiences(session, intake_session.id)
    exact_by_key, title_by_key = experience_indexes(saved)
    for item in output.updated_draft_profile.experience_and_projects:
        title = meaningful_text(item.title)
        if not title:
            continue
        organization = meaningful_text(item.organization)
        summary = meaningful_text(item.summary)
        existing = exact_by_key.get(experience_key(title, organization)) or title_by_key.get(normalize_key(title))
        if existing is not None:
            if not meaningful_text(existing.organization) and organization:
                existing.organization = organization
            if not meaningful_text(existing.summary) and summary:
                existing.summary = summary
            if not meaningful_text(existing.start_date):
                existing.start_date = meaningful_text(item.start_date)
            if not meaningful_text(existing.end_date):
                existing.end_date = meaningful_text(item.end_date)
            if not meaningful_text(existing.location):
                existing.location = meaningful_text(item.location)
            existing.structured_value = {
                **(existing.structured_value if isinstance(existing.structured_value, dict) else {}),
                **experience_structured_value(item),
            }
            continue
        row = ExperienceProjectDraft(
            candidate_profile_id=candidate_profile.id,
            profile_intake_session_id=intake_session.id,
            title=title,
            organization=organization,
            start_date=meaningful_text(item.start_date),
            end_date=meaningful_text(item.end_date),
            location=meaningful_text(item.location),
            summary=summary or "",
            source=item.source,
            visibility="private",
            review_status="needs_review",
            publication_status="not_published",
            structured_value=experience_structured_value(item),
        )
        session.add(row)
        saved.append(row)
        exact_by_key[experience_key(title, organization)] = row
        title_by_key = rebuild_unique_title_index(saved)
    return saved


def merge_evidence_links(
    session: Session,
    candidate_profile: CandidateProfile,
    intake_session: ProfileIntakeSession,
    output: ProfileIntakeOutput,
) -> list[EvidenceArtifact]:
    saved = get_session_evidence(session, intake_session.id)
    existing_by_key = {evidence_key(row.uri, row.label): row for row in saved}
    for link in output.updated_draft_profile.evidence_links:
        url = meaningful_text(link.url)
        label = meaningful_text(link.label)
        if not url and not label:
            continue
        key = evidence_key(url, label)
        existing = existing_by_key.get(key)
        if existing is not None:
            if label and (not meaningful_text(existing.label) or existing.label == existing.uri):
                existing.label = label
            continue
        row = EvidenceArtifact(
            candidate_profile_id=candidate_profile.id,
            profile_intake_session_id=intake_session.id,
            artifact_type="link",
            label=label or url or "Evidence link",
            uri=url,
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
        existing_by_key[key] = row
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
        "draftFacts": [serialize_fact_draft(fact) for fact in facts],
        "skillClaims": [serialize_skill_claim(skill) for skill in skills],
        "experienceAndProjects": [serialize_experience_project(item) for item in experiences],
        "evidenceLinks": [serialize_evidence_link(item) for item in evidence],
        "clarifyingQuestions": output.clarifying_questions,
        "changeSummary": output.change_summary,
        **({"noChangeReason": output.no_change_reason} if output.no_change_reason else {}),
    }


def serialize_role_target(role_target: RoleTarget | None, output: ProfileIntakeOutput) -> dict[str, Any]:
    if role_target is None:
        return output.updated_draft_profile.target_role_intent.model_dump(by_alias=True, exclude_none=True)

    constraints = role_target.constraints if isinstance(role_target.constraints, dict) else {}
    payload = {
        "targetTitles": join_text_list(role_target.target_titles),
        "targetRoleFamilies": join_text_list(role_target.role_families),
        "preferredWorkMode": role_target.work_modes[0] if role_target.work_modes else None,
        "preferredLocations": join_location_list(role_target.preferred_locations),
        "domainsOrIndustries": constraints.get("domainsOrIndustries"),
        "constraints": constraints.get("constraints"),
    }
    return {key: value for key, value in payload.items() if value}


def role_target_summary(output: ProfileIntakeOutput) -> str:
    intent = output.updated_draft_profile.target_role_intent
    values = [
        intent.target_titles,
        intent.target_role_families,
        intent.preferred_work_mode,
        intent.preferred_locations,
        intent.domains_or_industries,
        intent.constraints,
    ]
    return " | ".join(value for value in values if value)


def role_target_summary_from_row(role_target: RoleTarget | None) -> str:
    if role_target is None:
        return ""

    constraints = role_target.constraints if isinstance(role_target.constraints, dict) else {}
    values = [
        join_text_list(role_target.target_titles),
        join_text_list(role_target.role_families),
        join_text_list(role_target.work_modes),
        join_location_list(role_target.preferred_locations),
        constraints.get("domainsOrIndustries"),
        constraints.get("constraints"),
    ]
    return " | ".join(value for value in values if value)


def split_text_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.replace("|", ",").replace(";", ",").split(",") if part.strip()]


def split_location_text_list(value: str | None) -> list[str]:
    if not value:
        return []
    if ";" in value or "|" in value or "\n" in value:
        normalized = value.replace("|", ";").replace("\n", ";")
        return [part.strip() for part in normalized.split(";") if part.strip()]
    return [value.strip()] if value.strip() else []


def join_text_list(value: list[str] | None) -> str | None:
    if not value:
        return None
    return ", ".join(value)


def join_location_list(value: list[str] | None) -> str | None:
    if not value:
        return None
    return "; ".join(value)


def normalize_source(value: str | None) -> str:
    return value if value in {"chat", "resume", "model"} else "model"


def draft_count_metadata(output: ProfileIntakeOutput) -> dict[str, int]:
    draft = output.updated_draft_profile
    return {
        "draftFactCount": len(draft.draft_facts),
        "skillClaimCount": len(draft.skill_claims),
        "experienceAndProjectCount": len(draft.experience_and_projects),
        "evidenceLinkCount": len(draft.evidence_links),
    }


def draft_count_metadata_from_saved(
    *,
    facts: list[ProfileFactDraft],
    skills: list[SkillClaim],
    experiences: list[ExperienceProjectDraft],
    evidence: list[EvidenceArtifact],
) -> dict[str, int]:
    return {
        "draftFactCount": len(facts),
        "skillClaimCount": len(skills),
        "experienceAndProjectCount": len(experiences),
        "evidenceLinkCount": len(evidence),
    }


def get_active_role_target(session: Session, intake_session_id: str) -> RoleTarget | None:
    return session.scalar(
        select(RoleTarget)
        .where(RoleTarget.profile_intake_session_id == intake_session_id, RoleTarget.is_active.is_(True))
        .order_by(RoleTarget.updated_at.desc(), RoleTarget.created_at.desc())
    )


def get_session_facts(session: Session, intake_session_id: str) -> list[ProfileFactDraft]:
    return list(
        session.scalars(
            select(ProfileFactDraft)
            .where(ProfileFactDraft.profile_intake_session_id == intake_session_id)
            .order_by(ProfileFactDraft.created_at.asc())
        )
    )


def get_session_skills(session: Session, intake_session_id: str) -> list[SkillClaim]:
    return list(
        session.scalars(
            select(SkillClaim)
            .where(SkillClaim.profile_intake_session_id == intake_session_id)
            .order_by(SkillClaim.created_at.asc())
        )
    )


def get_session_experiences(session: Session, intake_session_id: str) -> list[ExperienceProjectDraft]:
    return list(
        session.scalars(
            select(ExperienceProjectDraft)
            .where(ExperienceProjectDraft.profile_intake_session_id == intake_session_id)
            .order_by(ExperienceProjectDraft.created_at.asc())
        )
    )


def get_session_evidence(session: Session, intake_session_id: str) -> list[EvidenceArtifact]:
    return list(
        session.scalars(
            select(EvidenceArtifact)
            .where(EvidenceArtifact.profile_intake_session_id == intake_session_id)
            .order_by(EvidenceArtifact.created_at.asc())
        )
    )


def serialize_fact_draft(fact: ProfileFactDraft) -> dict[str, Any]:
    structured_value = fact.structured_value if isinstance(fact.structured_value, dict) else {}
    return {
        "id": fact.id,
        "claim": fact.claim,
        "category": fact.fact_type,
        "source": normalize_source(fact.source),
        "status": fact.review_status,
        "visibility": fact.suggested_visibility,
        "published": bool(structured_value.get("published")),
    }


def serialize_skill_claim(skill: SkillClaim) -> dict[str, Any]:
    payload = {
        "id": skill.id,
        "skill": skill.skill_name,
        "category": skill.skill_category,
        "evidence": skill.evidence_summary,
        "yearsMin": skill.years_min,
        "yearsMax": skill.years_max,
        "source": normalize_source(skill.source),
        "status": skill.verification_status,
        "visibility": skill.visibility,
        "published": skill.publication_status == "published",
    }
    return {key: value for key, value in payload.items() if value is not None}


def serialize_experience_project(item: ExperienceProjectDraft) -> dict[str, Any]:
    structured_value = item.structured_value if isinstance(item.structured_value, dict) else {}
    payload = {
        "id": item.id,
        "itemType": structured_value.get("itemType") or "experience",
        "title": item.title,
        "organization": item.organization,
        "startDate": item.start_date or structured_value.get("startDate"),
        "endDate": item.end_date or structured_value.get("endDate"),
        "location": item.location or structured_value.get("location"),
        "summary": item.summary,
        "bullets": structured_value.get("bullets") if isinstance(structured_value.get("bullets"), list) else [],
        "source": normalize_source(item.source),
        "status": item.review_status,
        "visibility": item.visibility,
        "published": item.publication_status == "published" or bool(structured_value.get("published")),
    }
    return {key: value for key, value in payload.items() if value is not None}


def serialize_evidence_link(item: EvidenceArtifact) -> dict[str, Any]:
    artifact_metadata = item.artifact_metadata if isinstance(item.artifact_metadata, dict) else {}
    return {
        "id": item.id,
        "url": item.uri or "",
        "label": item.label,
        "source": normalize_source(item.source),
        "status": item.review_status,
        "visibility": item.visibility,
        "published": item.publication_status == "published" or bool(artifact_metadata.get("published")),
    }


def meaningful_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def apply_experience_fields(row: ExperienceProjectDraft, item) -> None:
    row.start_date = meaningful_text(item.start_date)
    row.end_date = meaningful_text(item.end_date)
    row.location = meaningful_text(item.location)


def experience_structured_value(item) -> dict[str, Any]:
    bullets = [bullet.strip() for bullet in item.bullets if isinstance(bullet, str) and bullet.strip()]
    return {
        "published": False,
        "sourceStatus": item.status,
        "itemType": item.item_type,
        **({"startDate": item.start_date} if meaningful_text(item.start_date) else {}),
        **({"endDate": item.end_date} if meaningful_text(item.end_date) else {}),
        **({"location": item.location} if meaningful_text(item.location) else {}),
        **({"bullets": bullets} if bullets else {}),
    }


def normalize_key(value: str | None) -> str:
    return " ".join((value or "").split()).casefold()


def normalize_url_key(value: str | None) -> str:
    return normalize_key((value or "").rstrip("/"))


def fact_key(claim: str | None, category: str | None) -> str:
    return f"{normalize_key(category or 'general')}:{normalize_key(claim)}"


def skill_key(skill_name: str | None, category: str | None) -> str:
    return f"{normalize_key(category or 'general')}:{normalize_key(skill_name)}"


def experience_key(title: str | None, organization: str | None) -> str:
    title_key = normalize_key(title)
    organization_key = normalize_key(organization)
    return f"{title_key}:{organization_key}" if organization_key else title_key


def experience_indexes(
    rows: list[ExperienceProjectDraft],
) -> tuple[dict[str, ExperienceProjectDraft], dict[str, ExperienceProjectDraft]]:
    return ({experience_key(row.title, row.organization): row for row in rows}, rebuild_unique_title_index(rows))


def rebuild_unique_title_index(rows: list[ExperienceProjectDraft]) -> dict[str, ExperienceProjectDraft]:
    title_index: dict[str, ExperienceProjectDraft | None] = {}
    for row in rows:
        key = normalize_key(row.title)
        title_index[key] = row if key not in title_index else None
    return {key: row for key, row in title_index.items() if row is not None}


def evidence_key(url: str | None, label: str | None) -> str:
    url_key = normalize_url_key(url)
    if url_key:
        return f"url:{url_key}"
    return f"label:{normalize_key(label)}"
