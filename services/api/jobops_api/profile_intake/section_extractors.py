from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from ..model_connector import ModelConnector, ModelMessage, ModelProviderError, ModelRequest, ModelResponse
from ..model_connector.config import ModelConnectorConfig
from ..model_connector.routing import route_model_request
from .context import ProfileIntakeContextBundle
from .intake_mode import detect_profile_intake_mode
from .models import ProfileIntakeOutput, ProfileIntakeSection, ProfileIntakeSectionOutput


SECTION_EXTRACTOR_PROMPT_VERSION = "profile-intake-section-extractors-v1"
SECTION_EXTRACTOR_SCHEMA_NAME = "jobops_profile_intake_section"
SECTION_EXTRACTOR_SCHEMA_VERSION = "profile-intake-section-output-v1"
SECTION_EXTRACTOR_MAX_OUTPUT_TOKENS = {
    "basics_and_targets": 2200,
    "skills": 2600,
    "experience_projects": 3600,
}
SECTION_EXTRACTOR_MAX_CHANGES = {
    "basics_and_targets": 6,
    "skills": 12,
    "experience_projects": 12,
}
SECTION_ORDER: tuple[ProfileIntakeSection, ...] = ("basics_and_targets", "skills", "experience_projects")


@dataclass(frozen=True)
class SectionExtractorSuccess:
    section: ProfileIntakeSection
    output: ProfileIntakeSectionOutput
    request: ModelRequest
    response: ModelResponse
    latency_ms: int


@dataclass(frozen=True)
class SectionExtractorFailure:
    section: ProfileIntakeSection
    issues: list[str]
    request: ModelRequest | None = None
    response: ModelResponse | None = None
    latency_ms: int = 0
    code: str = "model_output_invalid"


def extract_basics_and_targets(
    context: ProfileIntakeContextBundle,
    *,
    connector: ModelConnector,
    connector_config: ModelConnectorConfig,
) -> SectionExtractorSuccess:
    return run_section_extractor("basics_and_targets", context, connector=connector, connector_config=connector_config)


def extract_skills(
    context: ProfileIntakeContextBundle,
    *,
    connector: ModelConnector,
    connector_config: ModelConnectorConfig,
) -> SectionExtractorSuccess:
    return run_section_extractor("skills", context, connector=connector, connector_config=connector_config)


def extract_experience_projects(
    context: ProfileIntakeContextBundle,
    *,
    connector: ModelConnector,
    connector_config: ModelConnectorConfig,
) -> SectionExtractorSuccess:
    return run_section_extractor("experience_projects", context, connector=connector, connector_config=connector_config)


def run_section_extractor(
    section: ProfileIntakeSection,
    context: ProfileIntakeContextBundle,
    *,
    connector: ModelConnector,
    connector_config: ModelConnectorConfig,
) -> SectionExtractorSuccess:
    request = route_model_request(build_section_model_request(section, context), connector_config.routing)
    started_at = time.perf_counter()
    try:
        response = connector.generate(request)
    except ModelProviderError as error:
        latency_ms = round((time.perf_counter() - started_at) * 1000)
        raise SectionExtractorRuntimeError(
            SectionExtractorFailure(
                section=section,
                issues=[str(error)],
                request=request,
                latency_ms=latency_ms,
                code=error.code,
            )
        ) from error
    latency_ms = round((time.perf_counter() - started_at) * 1000)

    try:
        parsed = parse_section_json(response.text)
        output = parse_section_output(parsed, section)
        if output.section != section:
            raise SectionExtractorValidationError([f"section: Expected {section}, got {output.section}."])
    except SectionExtractorValidationError as error:
        raise SectionExtractorRuntimeError(
            SectionExtractorFailure(
                section=section,
                issues=add_truncation_hint(error.issues, response.finish_reason),
                request=request,
                response=response,
                latency_ms=latency_ms,
            )
        ) from error
    except ValidationError as error:
        raise SectionExtractorRuntimeError(
            SectionExtractorFailure(
                section=section,
                issues=add_truncation_hint(format_validation_issues(error), response.finish_reason),
                request=request,
                response=response,
                latency_ms=latency_ms,
            )
        ) from error

    return SectionExtractorSuccess(
        section=section,
        output=output,
        request=request,
        response=response,
        latency_ms=latency_ms,
    )


class SectionExtractorRuntimeError(Exception):
    def __init__(self, failure: SectionExtractorFailure) -> None:
        super().__init__("Profile intake section extractor failed.")
        self.failure = failure


class SectionExtractorValidationError(Exception):
    def __init__(self, issues: list[str]) -> None:
        super().__init__("Profile intake section output validation failed.")
        self.issues = issues


def build_section_model_request(section: ProfileIntakeSection, context: ProfileIntakeContextBundle) -> ModelRequest:
    intake_mode = detect_profile_intake_mode(context.latest_user_message)
    return ModelRequest(
        task="profile_draft_update",
        temperature=0,
        max_output_tokens=SECTION_EXTRACTOR_MAX_OUTPUT_TOKENS[section],
        response_mime_type="application/json",
        metadata={
            "feature": "profile_intake",
            "intake_mode": intake_mode,
            "profile_intake_contract": "section_extractor",
            "profile_intake_section": section,
            "authoritative_current_draft_source": context.authoritative_current_draft_source,
            "client_existing_draft_included": context.client_existing_draft is not None,
            "prompt_version": SECTION_EXTRACTOR_PROMPT_VERSION,
            "schema_name": SECTION_EXTRACTOR_SCHEMA_NAME,
            "schema_version": SECTION_EXTRACTOR_SCHEMA_VERSION,
        },
        messages=[
            ModelMessage(role="system", content=section_system_prompt(section)),
            ModelMessage(role="user", content=build_section_user_prompt(section, context)),
        ],
    )


def section_system_prompt(section: ProfileIntakeSection) -> str:
    labels = {
        "basics_and_targets": "profile basics and target-role preferences",
        "skills": "skill claims only",
        "experience_projects": "experience, projects, education, certifications, and evidence links",
    }
    allowed_targets = {
        "basics_and_targets": "profileBasics and targetRoleIntent",
        "skills": "skillClaims",
        "experience_projects": "draftFacts, experienceAndProjects, and evidenceLinks",
    }
    return f"""You are a JobOps Profile Intake section extractor for {labels[section]}.

Return strict JSON only. You are only extracting or proposing updates for this one section.

Rules:
- Use the user message, transcript/context, resume/document text, and existing profile state.
- Do not duplicate facts already present.
- Do not remove or clear data unless the user explicitly requested removal. In Phase 1, do not perform clear/archive actions; report that a clear request was detected in userUpdate or candidateFollowUpQuestions.
- Return no_changes if there is no reliable new information for this section.
- Return section_complete if this section already appears complete based on current profile state and new context.
- Do not include profile fields outside this section. Allowed change targets: {allowed_targets[section]}.
- Preserve user intent and avoid over-normalizing.
- Do not invent missing facts.
- Do not mark anything verified, public, approved, or published.
- For generated items, include source as chat, resume, or model; status as draft or needs_review; visibility as private; and published as false.
- Return at most {SECTION_EXTRACTOR_MAX_CHANGES[section]} changes for this section. Prefer the strongest, least duplicative evidence.
- Each changes item must have value as one object, not an array. If you have multiple items, create multiple changes with the same target.
{section_specific_output_rule(section)}

Return exactly this JSON shape:
{{
  "section": "{section}",
  "status": "changes_proposed",
  "changes": [
    {{
      "target": "{next(iter(allowed_targets[section].split(' and '))).split(',')[0]}",
      "value": {{}}
    }}
  ],
  "noChangeReason": null,
  "sectionComplete": false,
  "confidence": "medium",
  "userUpdate": "Short UI-safe update for this section.",
  "candidateFollowUpQuestions": [
    {{"question": "A concise follow-up question?", "reason": "Why it helps.", "priority": 10}}
  ]
}}"""


def section_specific_output_rule(section: ProfileIntakeSection) -> str:
    if section == "skills":
        return (
            "- For skills, group related technologies into high-signal claims. Do not enumerate every resume keyword "
            "as a separate skill claim."
        )
    if section == "experience_projects":
        return (
            "- For experience/projects, each role, project, education item, certification, fact, or link must be its "
            "own change object."
        )
    return "- For basics and targets, include only direct profile basics or target-role preference changes."


def build_section_user_prompt(section: ProfileIntakeSection, context: ProfileIntakeContextBundle) -> str:
    intake_mode = detect_profile_intake_mode(context.latest_user_message)
    return json.dumps(
        {
            "task": "extract_profile_intake_section",
            "section": section,
            "detected_intake_mode": intake_mode,
            "latest_user_message": context.latest_user_message,
            "authoritative_current_draft_source": context.authoritative_current_draft_source,
            "authoritative_current_draft": context.current_generated_draft_profile,
            "client_existing_draft": context.client_existing_draft,
            "profile_intake_context": context.model_dump(by_alias=True, exclude_none=True),
            "update_rules": {
                "return_full_updated_draft": False,
                "backend_interprets_additive_or_replacement_language": True,
                "target_role_intent_update_contract": (
                    "Return only targetRoleIntent changes for this section. Preserve current values unless the user "
                    "clearly changes them; do not update unrelated sections."
                ),
            },
            "change_contract": {
                "changes_are_incremental": True,
                "do_not_return_full_profile": True,
                "max_changes": SECTION_EXTRACTOR_MAX_CHANGES[section],
                "value_must_be_object": True,
                "arrays_must_be_split_into_individual_changes": True,
                "allowed_targets": {
                    "basics_and_targets": ["profileBasics", "targetRoleIntent"],
                    "skills": ["skillClaims"],
                    "experience_projects": ["draftFacts", "experienceAndProjects", "evidenceLinks"],
                }[section],
                "target_payload_shapes": {
                    "profileBasics": {
                        "displayName": "string",
                        "headline": "string",
                        "summary": "string",
                        "emailAddress": "string",
                        "telephoneNumber": "string",
                        "calendlyLink": "string",
                        "currentLocation": "string",
                        "mailingAddress": "string",
                    },
                    "targetRoleIntent": {
                        "targetTitles": "string",
                        "targetRoleFamilies": "string",
                        "preferredWorkMode": "remote|hybrid|onsite|flexible",
                        "preferredLocations": "string",
                        "domainsOrIndustries": "string",
                        "constraints": "string",
                    },
                    "draftFacts": "one DraftFact object",
                    "skillClaims": "one SkillClaim object",
                    "experienceAndProjects": "one ExperienceAndProject object",
                    "evidenceLinks": "one EvidenceLink object",
                },
            },
        },
        indent=2,
    )


def build_mock_profile_intake_section_response(request: ModelRequest) -> str:
    prompt_payload = extract_user_prompt_payload(request)
    section = prompt_payload.get("section")
    latest_user_message = extract_latest_user_message_from_payload(prompt_payload)
    changes = build_mock_section_changes(section, latest_user_message)

    status = "changes_proposed" if changes else "no_changes"
    return json.dumps(
        {
            "section": section,
            "status": status,
            "changes": changes,
            "noChangeReason": None if changes else "No reliable new information for this section.",
            "sectionComplete": False,
            "confidence": "medium",
            "userUpdate": section_user_update(section, len(changes)),
            "candidateFollowUpQuestions": [
                {
                    "question": "What measurable outcome should I attach to the strongest example?",
                    "reason": "Measurable outcomes make generated profile drafts easier to review and publish.",
                    "priority": 20,
                }
            ],
        }
    )


def extract_user_prompt_payload(request: ModelRequest) -> dict[str, Any]:
    for message in reversed(request.messages):
        if message.role != "user":
            continue
        try:
            parsed = json.loads(message.content)
        except json.JSONDecodeError:
            return {"latest_user_message": message.content}
        return parsed if isinstance(parsed, dict) else {"latest_user_message": message.content}
    return {}


def extract_latest_user_message_from_payload(payload: dict[str, Any]) -> str:
    latest_user_message = payload.get("latest_user_message") or payload.get("latestUserMessage")
    return latest_user_message if isinstance(latest_user_message, str) else ""


def build_mock_section_changes(section: object, message: str) -> list[dict[str, Any]]:
    if section == "basics_and_targets":
        return build_mock_basics_and_targets_changes(message)
    if section == "skills":
        return build_mock_skill_changes(message)
    if section == "experience_projects":
        return build_mock_experience_project_changes(message)
    return []


def build_mock_basics_and_targets_changes(message: str) -> list[dict[str, Any]]:
    lower = message.lower()
    target: dict[str, Any] = {}
    title = extract_target_title(message)
    if title:
        target["targetTitles"] = title
    if "remote" in lower:
        target["preferredWorkMode"] = "remote"
    elif "hybrid" in lower:
        target["preferredWorkMode"] = "hybrid"
    elif "onsite" in lower or "on-site" in lower:
        target["preferredWorkMode"] = "onsite"
    return [{"target": "targetRoleIntent", "value": target}] if target else []


def build_mock_skill_changes(message: str) -> list[dict[str, Any]]:
    lower = message.lower()
    skill_specs = [
        ("Python", "programming", ["python"]),
        ("TypeScript", "programming", ["typescript"]),
        ("React", "frontend", ["react"]),
        ("FastAPI", "backend", ["fastapi"]),
        ("Postgres", "data", ["postgres", "postgresql"]),
        ("LLM systems", "ai_systems", ["llm", "agent", "rag", "prompt"]),
        ("Evals and reliability", "quality", ["eval", "observability", "monitor", "test"]),
    ]
    changes = []
    for skill, category, keywords in skill_specs:
        if any(keyword in lower for keyword in keywords):
            changes.append(
                {
                    "target": "skillClaims",
                    "value": generated_mock_item(
                        {
                            "skill": skill,
                            "category": category,
                            "evidence": "Keyword evidence found in deterministic local mock mode.",
                            "source": mock_source_for_message(message),
                        }
                    ),
                }
            )
    return changes


def build_mock_experience_project_changes(message: str) -> list[dict[str, Any]]:
    if not looks_like_experience_or_resume(message):
        return []
    source = mock_source_for_message(message)
    title = first_interesting_line(message) or "Experience or project draft"
    changes = [
        {
            "target": "draftFacts",
            "value": generated_mock_item(
                {
                    "claim": extract_mock_fact_claim(message),
                    "category": "resume_evidence" if source == "resume" else "work_evidence",
                    "source": source,
                }
            ),
        },
        {
            "target": "experienceAndProjects",
            "value": generated_mock_item(
                {
                    "itemType": "project" if "project" in message.lower() else "experience",
                    "title": title[:180],
                    "organization": "Needs review",
                    "summary": "Potential work, project, education, or artifact evidence detected from intake text.",
                    "bullets": [],
                    "source": source,
                }
            ),
        }
    ]
    for url in sorted(set(re.findall(r"https?://[^\s)]+", message)))[:6]:
        changes.append(
            {"target": "evidenceLinks", "value": generated_mock_item({"url": url, "label": url, "source": source})}
        )
    return changes


def extract_mock_fact_claim(message: str) -> str:
    for line in (line.strip(" -\t*") for line in message.splitlines()):
        clean_line = re.sub(r"\s+", " ", line).strip()
        if len(clean_line) >= 12 and re.search(r"built|shipped|led|created|developed|implemented", clean_line, re.I):
            return clean_line[:220]
    return "Potential work evidence detected from intake text."


def generated_mock_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        **item,
        "status": "needs_review",
        "visibility": "private",
        "published": False,
    }


def extract_target_title(message: str) -> str | None:
    match = re.search(r"i want to be an?\s+([^.\n]+)", message, flags=re.IGNORECASE)
    if not match:
        return None
    title = match.group(1).strip().rstrip(".!?").strip()
    return title or None


def looks_like_experience_or_resume(message: str) -> bool:
    lower = message.lower()
    lines = [line for line in message.splitlines() if line.strip()]
    return len(lines) >= 3 or any(
        keyword in lower
        for keyword in (
            "experience",
            "education",
            "skills",
            "projects",
            "certification",
            "i built",
            "i shipped",
            "i led",
            "i created",
            "i developed",
            "i implemented",
            "built a",
            "built an",
            "shipped a",
            "project:",
            "open source",
            "publication",
        )
    )


def mock_source_for_message(message: str) -> str:
    lower = message.lower()
    lines = [line for line in message.splitlines() if line.strip()]
    if len(lines) >= 3 or any(keyword in lower for keyword in ("experience", "education", "skills", "projects")):
        return "resume"
    return "chat"


def first_interesting_line(message: str) -> str | None:
    for line in (line.strip(" -\t*") for line in message.splitlines()):
        if re.search(r"engineer|developer|consultant|architect|lead|project|education|certification", line, re.I):
            return re.sub(r"\s+", " ", line).strip()[:90]
    return None


def build_prompt_artifact(request: ModelRequest) -> str:
    return "\n\n".join(f"{message.role.upper()}:\n{message.content}" for message in request.messages)


def parse_section_output(parsed: Any, section: ProfileIntakeSection) -> ProfileIntakeSectionOutput:
    if isinstance(parsed, dict) and isinstance(parsed.get("updatedDraftProfile"), dict):
        return adapt_full_profile_output_to_section(parsed, section)
    return ProfileIntakeSectionOutput.model_validate(normalize_section_change_values(parsed))


def normalize_section_change_values(parsed: Any) -> Any:
    if not isinstance(parsed, dict) or not isinstance(parsed.get("changes"), list):
        return parsed

    normalized_changes: list[Any] = []
    changed = False
    for change in parsed["changes"]:
        if not isinstance(change, dict):
            normalized_changes.append(change)
            continue
        if not isinstance(change.get("value"), list):
            normalized_change = normalize_section_change_value(change)
            normalized_changes.append(normalized_change)
            changed = changed or normalized_change is not change
            continue
        target = change.get("target")
        for item in change["value"]:
            normalized_changes.append(normalize_section_change_value({"target": target, "value": item}))
        changed = True

    if not changed:
        return parsed
    return {**parsed, "changes": normalized_changes}


def normalize_section_change_value(change: dict[str, Any]) -> dict[str, Any]:
    value = change.get("value")
    if change.get("target") == "skillClaims" and isinstance(value, dict) and "skill" not in value and "skillName" in value:
        return {**change, "value": {key: item for key, item in {**value, "skill": value["skillName"]}.items() if key != "skillName"}}
    return change


def adapt_full_profile_output_to_section(parsed: dict[str, Any], section: ProfileIntakeSection) -> ProfileIntakeSectionOutput:
    full_output = ProfileIntakeOutput.model_validate(parsed)
    draft = full_output.updated_draft_profile.model_dump(by_alias=True, exclude_none=True)
    changes: list[dict[str, Any]] = []
    if section == "basics_and_targets":
        basics = draft.get("profileBasics")
        target = draft.get("targetRoleIntent")
        if isinstance(basics, dict) and basics:
            changes.append({"target": "profileBasics", "value": basics})
        if isinstance(target, dict) and target:
            changes.append({"target": "targetRoleIntent", "value": target})
    elif section == "skills":
        for item in draft.get("skillClaims") or []:
            if isinstance(item, dict):
                changes.append({"target": "skillClaims", "value": item})
    elif section == "experience_projects":
        for target_name in ("draftFacts", "experienceAndProjects", "evidenceLinks"):
            for item in draft.get(target_name) or []:
                if isinstance(item, dict):
                    changes.append({"target": target_name, "value": item})

    return ProfileIntakeSectionOutput.model_validate(
        {
            "section": section,
            "status": "changes_proposed" if changes else "no_changes",
            "changes": changes,
            "noChangeReason": full_output.no_change_reason,
            "sectionComplete": False,
            "confidence": "medium",
            "userUpdate": full_output.assistant_message,
            "candidateFollowUpQuestions": [
                {"question": question, "reason": "Provider output clarifying question.", "priority": 10}
                for question in full_output.clarifying_questions[:3]
            ],
        }
    )


def section_user_update(section: object, change_count: int) -> str:
    if change_count <= 0:
        return "I did not find reliable new information for this section."
    if section == "basics_and_targets":
        return "I found profile basics or target-role updates to add to your draft."
    if section == "skills":
        return "I found skill claims to add to your draft."
    if section == "experience_projects":
        return "I found experience, project, or evidence updates to add to your draft."
    return "I found profile draft updates."


def parse_section_json(raw_text: str) -> Any:
    stripped = raw_text.strip()
    candidates = [stripped]
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            candidates.append("\n".join(lines[1:-1]).strip())
    extracted = extract_first_json_object(stripped)
    if extracted and extracted not in candidates:
        candidates.append(extracted)
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise SectionExtractorValidationError(["Output is not valid JSON."])


def extract_first_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None


def format_validation_issues(error: ValidationError) -> list[str]:
    issues = []
    for item in error.errors():
        path = ".".join(str(part) for part in item.get("loc", ())) or "Output"
        issues.append(f"{path}: {item.get('msg', 'Invalid value')}")
    return issues


def add_truncation_hint(issues: list[str], finish_reason: str | None) -> list[str]:
    if finish_reason and ("max" in finish_reason.lower() or "length" in finish_reason.lower() or "token" in finish_reason.lower()):
        return [*issues, "Model response appears to have been truncated before valid JSON completed."]
    return issues
