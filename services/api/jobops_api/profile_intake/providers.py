from __future__ import annotations

import json
import re
from typing import Any

from ..model_connector import ModelRequest


def build_mock_profile_intake_response(request: ModelRequest) -> str:
    prompt_payload = extract_user_prompt_payload(request)
    latest_user_message = extract_latest_user_message_from_payload(prompt_payload)
    current_draft = prompt_payload.get("authoritative_current_draft") if isinstance(prompt_payload, dict) else None
    return json.dumps(build_mock_profile_intake_output(latest_user_message, current_draft))


def extract_user_prompt_payload(request: ModelRequest) -> dict[str, Any]:
    for message in reversed(request.messages):
        if message.role != "user":
            continue
        try:
            parsed = json.loads(message.content)
        except json.JSONDecodeError:
            return {"latest_user_message": message.content, "authoritative_current_draft": {}}
        return parsed if isinstance(parsed, dict) else {"latest_user_message": message.content}
    return {}


def extract_latest_user_message(request: ModelRequest) -> str:
    return extract_latest_user_message_from_payload(extract_user_prompt_payload(request))


def extract_latest_user_message_from_payload(payload: dict[str, Any]) -> str:
    latest_user_message = payload.get("latest_user_message") or payload.get("latestUserMessage")
    return latest_user_message if isinstance(latest_user_message, str) else ""


def legacy_extract_latest_user_message(request: ModelRequest) -> str:
    for message in reversed(request.messages):
        if message.role != "user":
            continue
        try:
            parsed = json.loads(message.content)
        except json.JSONDecodeError:
            return message.content

        if isinstance(parsed, dict):
            latest_user_message = parsed.get("latest_user_message") or parsed.get("latestUserMessage")
            if isinstance(latest_user_message, str):
                return latest_user_message
        return message.content

    return ""


def build_mock_profile_intake_output(message: str, current_draft: object = None) -> dict[str, Any]:
    updated_draft = normalize_current_draft(current_draft)
    lower = message.lower()
    is_resume_like = looks_like_resume_or_work_history(message)
    is_past_work_like = looks_like_past_work(message)
    should_extract_profile_items = is_resume_like or is_past_work_like
    source = "resume" if is_resume_like else "chat" if is_past_work_like else "model"
    title = extract_target_title(message)
    mentions_ai = mentions_any(lower, ["ai", "llm", "agent", "automation", "machine learning", "rag", "eval"])
    mentions_backend = mentions_any(lower, ["python", "fastapi", "api", "backend", "typescript", "postgres"])
    mentions_reliability = mentions_any(lower, ["eval", "test", "monitor", "observability", "reliability"])
    links = sorted(set(re.findall(r"https?://[^\s)]+", message)))

    draft_facts = []
    if should_extract_profile_items:
        if mentions_ai:
            draft_facts.append(
                generated_item(
                    {
                        "claim": "Intake text appears to mention AI, LLM, automation, agentic, or machine-learning work.",
                        "category": "applied_ai",
                        "source": source,
                    }
                )
            )
        if mentions_backend:
            draft_facts.append(
                generated_item(
                    {
                        "claim": "Intake text appears to mention backend, API, Python, TypeScript, Postgres, or FastAPI work.",
                        "category": "engineering",
                        "source": source,
                    }
                )
            )
        if mentions_reliability:
            draft_facts.append(
                generated_item(
                    {
                        "claim": "Intake text appears to mention evals, tests, monitoring, observability, or reliability work.",
                        "category": "reliability",
                        "source": source,
                    }
                )
            )

    skill_claims = []
    if should_extract_profile_items:
        skill_claims.extend(skill_if(lower, "Python", "programming", ["python"], source))
        skill_claims.extend(skill_if(lower, "FastAPI", "backend", ["fastapi"], source))
        skill_claims.extend(skill_if(lower, "LLM systems", "ai_systems", ["llm", "agent", "rag", "prompt"], source))
        skill_claims.extend(
            skill_if(lower, "Evals and reliability", "quality", ["eval", "monitor", "observability", "test"], source)
        )
        skill_claims.extend(skill_if(lower, "Postgres", "data", ["postgres", "postgresql", "sql"], source))

    experience_and_projects = []
    if should_extract_profile_items:
        experience_and_projects.append(
            generated_item(
                {
                    "title": first_interesting_line(message) or "Experience or project draft",
                    "organization": "Needs review",
                    "summary": "Potential work, project, education, or artifact evidence detected from intake text.",
                    "source": source,
                }
            )
        )

    target_role_intent = {
        **(updated_draft.get("targetRoleIntent") if isinstance(updated_draft.get("targetRoleIntent"), dict) else {}),
        **({"targetTitles": title} if title else {}),
        **({"targetRoleFamilies": "Applied AI, LLM systems, and forward-deployed engineering"} if mentions_ai else {}),
        **({"preferredWorkMode": "remote"} if "remote" in lower else {}),
        **({"preferredWorkMode": "hybrid"} if "hybrid" in lower else {}),
        **({"domainsOrIndustries": "developer tools"} if "developer tools" in lower else {}),
    }

    updated_draft = {
        "targetRoleIntent": {key: value for key, value in target_role_intent.items() if value},
        "draftFacts": append_unique_items(updated_draft.get("draftFacts"), draft_facts[:4], "claim"),
        "skillClaims": append_unique_items(updated_draft.get("skillClaims"), skill_claims[:6], "skill"),
        "experienceAndProjects": append_unique_items(
            updated_draft.get("experienceAndProjects"),
            experience_and_projects[:3],
            "title",
        ),
        "evidenceLinks": append_unique_items(updated_draft.get("evidenceLinks"), [generated_item({"url": url, "label": url, "source": source}) for url in links[:4]], "url"),
    }

    return {
        "assistantMessage": (
            "I drafted profile updates from your message. Everything is private and needs review. "
            "Next, tell me about measurable outcomes or production constraints."
            if draft_facts or skill_claims or experience_and_projects
            else "I captured your target direction. Next, paste your resume or describe a shipped project so I can draft evidence-backed profile items."
        ),
        "updatedDraftProfile": updated_draft,
        "clarifyingQuestions": [
            "What AI, automation, or agentic products have you shipped beyond a prototype?",
            "Which production constraints did you handle: latency, cost, safety, observability, or failure recovery?",
            "What measurable outcome can we attach to your strongest example?",
        ],
        "changeSummary": [
            "Updated target role intent." if title else "Target role intent still needs detail.",
            (
                f"Created {len(draft_facts[:4])} draft claim(s), {len(skill_claims[:6])} skill claim(s), "
                f"and {len(experience_and_projects[:3])} experience/project item(s)."
            ),
            "Kept all generated data private, unpublished, and marked for review.",
        ],
        "noChangeReason": None,
        "removedItems": {
            "draftFactIds": [],
            "skillClaimIds": [],
            "experienceAndProjectIds": [],
            "evidenceLinkIds": [],
            "targetRoleIntentFields": [],
        },
    }


def normalize_current_draft(current_draft: object) -> dict[str, Any]:
    draft = current_draft if isinstance(current_draft, dict) else {}
    return {
        "targetRoleIntent": draft.get("targetRoleIntent") if isinstance(draft.get("targetRoleIntent"), dict) else {},
        "draftFacts": draft.get("draftFacts") if isinstance(draft.get("draftFacts"), list) else [],
        "skillClaims": draft.get("skillClaims") if isinstance(draft.get("skillClaims"), list) else [],
        "experienceAndProjects": draft.get("experienceAndProjects") if isinstance(draft.get("experienceAndProjects"), list) else [],
        "evidenceLinks": draft.get("evidenceLinks") if isinstance(draft.get("evidenceLinks"), list) else [],
    }


def append_unique_items(existing: object, incoming: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    items = [item for item in existing if isinstance(item, dict)] if isinstance(existing, list) else []
    seen = {normalize_key(item.get(key)) for item in items if isinstance(item.get(key), str)}
    for item in incoming:
        item_key = normalize_key(item.get(key))
        if item_key and item_key in seen:
            continue
        if item_key:
            seen.add(item_key)
        items.append(item)
    return items


def generated_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        **item,
        "status": "needs_review",
        "visibility": "private",
        "published": False,
    }


def skill_if(lower_text: str, skill: str, category: str, keywords: list[str], source: str) -> list[dict[str, Any]]:
    if not mentions_any(lower_text, keywords):
        return []
    return [
        generated_item(
            {
                "skill": skill,
                "category": category,
                "evidence": "Keyword evidence found in unverified intake text.",
                "source": source,
            }
        )
    ]


def extract_target_title(message: str) -> str | None:
    match = re.search(r"i want to be an?\s+([^.\n]+)", message, flags=re.IGNORECASE)
    if not match:
        return None
    title = match.group(1).strip()
    if title == "...":
        return None
    return title.rstrip(".!?").strip()


def first_interesting_line(message: str) -> str | None:
    for line in (line.strip() for line in message.splitlines()):
        if re.search(r"engineer|developer|consultant|architect|lead|project|education|certification", line, re.I):
            return line[:90]
    return None


def looks_like_resume_or_work_history(message: str) -> bool:
    lower = message.lower()
    lines = [line for line in message.splitlines() if line.strip()]
    return len(lines) >= 3 or mentions_any(
        lower,
        [
            "experience",
            "education",
            "skills",
            "projects",
            "certification",
            "github",
            "linkedin",
            "work history",
        ],
    )


def looks_like_past_work(message: str) -> bool:
    return mentions_any(
        message.lower(),
        [
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
            "certification",
        ],
    )


def mentions_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def normalize_key(value: object) -> str:
    return " ".join(value.split()).casefold() if isinstance(value, str) else ""
