from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from ..model_connector import ModelConnector
from ..model_connector.config import ModelConnectorConfig
from .context import ProfileIntakeContextBundle
from .models import (
    DraftFact,
    EvidenceLink,
    ExperienceAndProject,
    ProfileBasics,
    ProfileIntakeOutput,
    ProfileIntakeSection,
    ProfileIntakeSectionChange,
    ProfileIntakeSectionOutput,
    RemovedDraftItems,
    SkillClaim,
    TargetRoleIntent,
    UpdatedDraftProfile,
)
from .section_extractors import (
    SECTION_ORDER,
    SectionExtractorFailure,
    SectionExtractorRuntimeError,
    SectionExtractorSuccess,
    extract_basics_and_targets,
    extract_experience_projects,
    extract_skills,
)


logger = logging.getLogger(__name__)
FAILED_RESPONSE_LOG_LINE_COUNT = 12


@dataclass(frozen=True)
class ProfileIntakeOrchestratorResult:
    output: ProfileIntakeOutput | None
    successes: list[SectionExtractorSuccess]
    failures: list[SectionExtractorFailure]
    latency_ms: int


def run_profile_intake_orchestrator(
    context: ProfileIntakeContextBundle,
    *,
    connector: ModelConnector,
    connector_config: ModelConnectorConfig,
    sections: tuple[ProfileIntakeSection, ...] = SECTION_ORDER,
) -> ProfileIntakeOrchestratorResult:
    started_at = time.perf_counter()
    successes: list[SectionExtractorSuccess] = []
    failures: list[SectionExtractorFailure] = []

    for section in sections:
        try:
            successes.append(run_section(section, context, connector=connector, connector_config=connector_config))
        except SectionExtractorRuntimeError as error:
            failures.append(error.failure)
            logger.warning(
                "[profile_intake] section extractor failed section=%s code=%s issues=%s diagnostics=%s",
                error.failure.section,
                error.failure.code,
                error.failure.issues,
                section_failure_diagnostics(error.failure, context),
            )

    output = build_profile_intake_output(context, [success.output for success in successes]) if successes else None
    return ProfileIntakeOrchestratorResult(
        output=output,
        successes=successes,
        failures=failures,
        latency_ms=round((time.perf_counter() - started_at) * 1000),
    )


def run_section(
    section: ProfileIntakeSection,
    context: ProfileIntakeContextBundle,
    *,
    connector: ModelConnector,
    connector_config: ModelConnectorConfig,
) -> SectionExtractorSuccess:
    if section == "basics_and_targets":
        return extract_basics_and_targets(context, connector=connector, connector_config=connector_config)
    if section == "skills":
        return extract_skills(context, connector=connector, connector_config=connector_config)
    return extract_experience_projects(context, connector=connector, connector_config=connector_config)


def build_profile_intake_output(
    context: ProfileIntakeContextBundle,
    section_outputs: list[ProfileIntakeSectionOutput],
) -> ProfileIntakeOutput:
    draft = normalized_current_draft(context.current_generated_draft_profile)
    changed_sections: list[str] = []

    for section_output in section_outputs:
        before = draft_signature(draft)
        for change in section_output.changes:
            apply_section_change(draft, section_output.section, change)
        if draft_signature(draft) != before:
            changed_sections.append(section_output.section)

    question = select_follow_up_question(section_outputs)
    user_updates = [output.user_update for output in section_outputs if output.user_update]
    assistant_message = combined_assistant_message(user_updates, question)
    no_change_reason = None if changed_sections else combined_no_change_reason(section_outputs)

    output = ProfileIntakeOutput(
        assistantMessage=assistant_message,
        updatedDraftProfile=UpdatedDraftProfile.model_validate(draft),
        clarifyingQuestions=[question["question"]] if question else [],
        changeSummary=change_summary(section_outputs, changed_sections),
        noChangeReason=no_change_reason,
        removedItems=RemovedDraftItems(),
    )
    return output


def normalized_current_draft(current_draft: dict[str, Any]) -> dict[str, Any]:
    draft = current_draft if isinstance(current_draft, dict) else {}
    return {
        "profileBasics": normalized_profile_basics(draft.get("profileBasics")),
        "targetRoleIntent": normalized_target_role_intent(draft.get("targetRoleIntent")),
        "draftFacts": normalized_items(draft.get("draftFacts"), DraftFact, fact_key),
        "skillClaims": normalized_items(draft.get("skillClaims"), SkillClaim, skill_key),
        "experienceAndProjects": normalized_items(
            draft.get("experienceAndProjects"),
            ExperienceAndProject,
            experience_key,
        ),
        "evidenceLinks": normalized_items(draft.get("evidenceLinks"), EvidenceLink, evidence_key),
    }


def normalized_profile_basics(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    allowed = set(ProfileBasics.model_fields)
    aliases = {field.alias or name: field.alias or name for name, field in ProfileBasics.model_fields.items()}
    payload = {aliases[key]: item for key, item in value.items() if key in aliases and meaningful_text(item)}
    return ProfileBasics.model_validate(payload).model_dump(by_alias=True, exclude_none=True)


def normalized_target_role_intent(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    aliases = {field.alias or name: field.alias or name for name, field in TargetRoleIntent.model_fields.items()}
    payload = {aliases[key]: item for key, item in value.items() if key in aliases and meaningful_text(item)}
    return TargetRoleIntent.model_validate(payload).model_dump(by_alias=True, exclude_none=True)


def normalized_items(value: object, model_class, key_func) -> list[dict[str, Any]]:
    items = value if isinstance(value, list) else []
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        payload = sanitize_generated_item(item)
        try:
            validated = model_class.model_validate(payload).model_dump(by_alias=True, exclude_none=True)
        except ValidationError:
            continue
        key = key_func(validated)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        normalized.append(validated)
    return normalized


def sanitize_generated_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        **item,
        "source": normalize_source(item.get("source")),
        "status": "needs_review" if item.get("status") != "draft" else "draft",
        "visibility": "private",
        "published": False,
    }


def apply_section_change(
    draft: dict[str, Any],
    section: ProfileIntakeSection,
    change: ProfileIntakeSectionChange,
) -> None:
    if section == "basics_and_targets" and change.target == "profileBasics":
        draft["profileBasics"] = merge_profile_object(draft["profileBasics"], change.value, ProfileBasics)
    elif section == "basics_and_targets" and change.target == "targetRoleIntent":
        draft["targetRoleIntent"] = merge_profile_object(draft["targetRoleIntent"], change.value, TargetRoleIntent)
    elif section == "skills" and change.target == "skillClaims":
        append_valid_item(draft["skillClaims"], change.value, SkillClaim, skill_key)
    elif section == "experience_projects" and change.target == "draftFacts":
        append_valid_item(draft["draftFacts"], change.value, DraftFact, fact_key)
    elif section == "experience_projects" and change.target == "experienceAndProjects":
        append_valid_item(draft["experienceAndProjects"], change.value, ExperienceAndProject, experience_key)
    elif section == "experience_projects" and change.target == "evidenceLinks":
        append_valid_item(draft["evidenceLinks"], change.value, EvidenceLink, evidence_key)


def merge_profile_object(existing: dict[str, Any], incoming: dict[str, Any], model_class) -> dict[str, Any]:
    aliases = {field.alias or name: field.alias or name for name, field in model_class.model_fields.items()}
    filtered = {aliases[key]: value for key, value in incoming.items() if key in aliases and meaningful_text(value)}
    if not filtered:
        return existing
    return model_class.model_validate({**existing, **filtered}).model_dump(by_alias=True, exclude_none=True)


def append_valid_item(items: list[dict[str, Any]], incoming: dict[str, Any], model_class, key_func) -> None:
    payload = sanitize_generated_item(incoming)
    try:
        validated = model_class.model_validate(payload).model_dump(by_alias=True, exclude_none=True)
    except ValidationError:
        return
    incoming_id = validated.get("id")
    if incoming_id:
        for index, item in enumerate(items):
            if item.get("id") == incoming_id:
                items[index] = validated
                return
    key = key_func(validated)
    if key and any(key_func(item) == key for item in items):
        return
    items.append(validated)


def select_follow_up_question(section_outputs: list[ProfileIntakeSectionOutput]) -> dict[str, Any] | None:
    tie_order = {"basics_and_targets": 0, "experience_projects": 1, "skills": 2}
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    for output in section_outputs:
        for question in output.candidate_follow_up_questions:
            candidates.append(
                (
                    question.priority,
                    -tie_order.get(output.section, 99),
                    question.model_dump(by_alias=True),
                )
            )
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[0], item[1]))[2]


def combined_assistant_message(user_updates: list[str], question: dict[str, Any] | None) -> str:
    useful_updates = [update.rstrip(".") for update in user_updates if update.strip()]
    if useful_updates:
        message = "; ".join(useful_updates[:3]) + "."
    else:
        message = "I reviewed your profile draft and did not find reliable new changes."
    if question:
        message = f"{message} Next: {question['question']}"
    return message


def combined_no_change_reason(section_outputs: list[ProfileIntakeSectionOutput]) -> str | None:
    reasons = []
    seen: set[str] = set()
    for output in section_outputs:
        if not output.no_change_reason or output.no_change_reason in seen:
            continue
        seen.add(output.no_change_reason)
        reasons.append(output.no_change_reason)
    return "; ".join(reasons[:3])[:300] if reasons else "No section extractor proposed reliable new profile changes."


def change_summary(section_outputs: list[ProfileIntakeSectionOutput], changed_sections: list[str]) -> list[str]:
    if not section_outputs:
        return ["No profile intake sections completed."]
    summaries = []
    for output in section_outputs:
        if output.status == "changes_proposed" and output.section in changed_sections:
            summaries.append(f"{section_label(output.section)} proposed {len(output.changes)} change(s).")
        elif output.status == "section_complete" or output.section_complete:
            summaries.append(f"{section_label(output.section)} appears complete.")
        elif output.status in {"no_changes", "needs_more_information"}:
            summaries.append(f"{section_label(output.section)} had no reliable new changes.")
    return summaries[:12] or ["No profile intake sections proposed reliable new changes."]


def section_label(section: ProfileIntakeSection) -> str:
    return {
        "basics_and_targets": "Basics and targets",
        "skills": "Skills",
        "experience_projects": "Experience and projects",
    }[section]


def section_failure_diagnostics(
    failure: SectionExtractorFailure,
    context: ProfileIntakeContextBundle,
) -> dict[str, Any]:
    request = failure.request
    response = failure.response
    response_text = response.text if response is not None else ""
    request_messages = request.messages if request is not None else []
    return {
        "section": failure.section,
        "code": failure.code,
        "sourceTextLength": len(context.latest_user_message) + len(context.resume_document_text or ""),
        "promptLength": sum(len(message.content) for message in request_messages),
        "provider": response.provider if response is not None else None,
        "model": (response.model if response is not None else None) or (request.model if request is not None else None),
        "maxOutputTokens": request.max_output_tokens if request is not None else None,
        "temperature": request.temperature if request is not None else None,
        "responseMimeType": request.response_mime_type if request is not None else None,
        "responseTextLength": len(response_text),
        "finishReason": response.finish_reason if response is not None else None,
        "parseStatus": "failed",
        **response_text_log_excerpt(response_text),
    }


def response_text_log_excerpt(text: str) -> dict[str, Any]:
    lines = text.splitlines() if text else []
    if not lines and text:
        lines = [text]
    if len(lines) <= FAILED_RESPONSE_LOG_LINE_COUNT * 2:
        return {
            "responseTextLineCount": len(lines),
            "responseTextLines": lines,
        }
    return {
        "responseTextLineCount": len(lines),
        "responseTextHeadLines": lines[:FAILED_RESPONSE_LOG_LINE_COUNT],
        "responseTextTailLines": lines[-FAILED_RESPONSE_LOG_LINE_COUNT:],
    }


def draft_signature(draft: dict[str, Any]) -> str:
    return json.dumps(draft, sort_keys=True, separators=(",", ":"), default=str)


def fact_key(item: dict[str, Any]) -> str:
    return f"{normalize_key(item.get('category') or 'general')}:{normalize_key(item.get('claim'))}"


def skill_key(item: dict[str, Any]) -> str:
    return f"{normalize_key(item.get('category') or 'general')}:{normalize_key(item.get('skill'))}"


def experience_key(item: dict[str, Any]) -> str:
    title = normalize_key(item.get("title"))
    organization = normalize_key(item.get("organization"))
    return f"{title}:{organization}" if organization else title


def evidence_key(item: dict[str, Any]) -> str:
    url = normalize_key(str(item.get("url") or "").rstrip("/"))
    if url:
        return f"url:{url}"
    return f"label:{normalize_key(item.get('label'))}"


def normalize_key(value: object) -> str:
    return " ".join(value.split()).casefold() if isinstance(value, str) else ""


def normalize_source(value: object) -> str:
    return value if value in {"chat", "resume", "model"} else "model"


def meaningful_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
