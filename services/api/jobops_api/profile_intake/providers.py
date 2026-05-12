from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from ..settings import Settings
from .models import ProfileIntakeExtractRequest


@dataclass(frozen=True)
class ModelRequest:
    task: str
    model: str
    system_prompt: str
    user_prompt: str
    temperature: float
    max_output_tokens: int
    latest_user_message: str
    existing_draft: dict[str, Any] | None


@dataclass(frozen=True)
class ModelResponse:
    text: str
    provider: str
    model: str
    finish_reason: str | None = None


class ProfileIntakeProvider(Protocol):
    def generate(self, request: ModelRequest) -> ModelResponse:
        ...


class ModelConfigurationError(Exception):
    code = "MODEL_CONFIG_ERROR"


class ModelProviderError(Exception):
    code = "MODEL_PROVIDER_ERROR"


class MockProfileIntakeProvider:
    def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            text=json.dumps(build_mock_profile_intake_output(request.latest_user_message)),
            provider="mock",
            model=request.model,
            finish_reason="stop",
        )


class GeminiProfileIntakeProvider:
    endpoint_base = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, api_key: str | None) -> None:
        if not api_key:
            raise ModelConfigurationError("GEMINI_API_KEY is required when JOBOPS_LLM_PROVIDER=gemini.")
        self._api_key = api_key

    def generate(self, request: ModelRequest) -> ModelResponse:
        encoded_model = urllib.parse.quote(request.model, safe="")
        url = f"{self.endpoint_base}/{encoded_model}:generateContent"
        payload = {
            "systemInstruction": {
                "parts": [{"text": request.system_prompt}],
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": request.user_prompt}],
                }
            ],
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_output_tokens,
                "responseMimeType": "application/json",
            },
        }
        body = json.dumps(payload).encode("utf-8")
        http_request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self._api_key,
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(http_request, timeout=60) as response:
                response_body = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:500]
            raise ModelProviderError(f"Gemini request failed with HTTP {error.code}: {detail}") from error
        except urllib.error.URLError as error:
            raise ModelProviderError(f"Gemini request failed: {error.reason}") from error

        data = parse_gemini_response_json(response_body)
        candidate = first_gemini_candidate(data)
        parts = gemini_candidate_parts(candidate)
        text = "\n".join(part["text"] for part in parts if isinstance(part.get("text"), str)).strip()
        if not text:
            raise ModelProviderError("Gemini response did not include text content.")

        return ModelResponse(
            text=text,
            provider="gemini",
            model=request.model,
            finish_reason=candidate.get("finishReason") if isinstance(candidate.get("finishReason"), str) else None,
        )


def create_profile_intake_provider(settings: Settings) -> ProfileIntakeProvider:
    provider = settings.model_provider.strip().lower()
    if provider == "mock":
        return MockProfileIntakeProvider()
    if provider == "gemini":
        return GeminiProfileIntakeProvider(settings.gemini_api_key)
    raise ModelConfigurationError(f"Unsupported JOBOPS_LLM_PROVIDER: {settings.model_provider}")


def build_model_request(
    request: ProfileIntakeExtractRequest,
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> ModelRequest:
    return ModelRequest(
        task="profile_extract",
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0,
        max_output_tokens=4000,
        latest_user_message=request.latest_user_message,
        existing_draft=request.existing_draft,
    )


def parse_gemini_response_json(response_body: str) -> dict[str, Any]:
    try:
        data = json.loads(response_body)
    except json.JSONDecodeError as error:
        raise ModelProviderError("Gemini response was not valid JSON.") from error

    if not isinstance(data, dict):
        raise ModelProviderError("Gemini response was not a JSON object.")

    return data


def first_gemini_candidate(data: dict[str, Any]) -> dict[str, Any]:
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ModelProviderError("Gemini response did not include candidates.")

    candidate = candidates[0]
    if not isinstance(candidate, dict):
        raise ModelProviderError("Gemini response candidate was not a JSON object.")

    return candidate


def gemini_candidate_parts(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    content = candidate.get("content")
    if not isinstance(content, dict):
        raise ModelProviderError("Gemini response candidate did not include content.")

    parts = content.get("parts")
    if not isinstance(parts, list):
        raise ModelProviderError("Gemini response content did not include parts.")

    return [part for part in parts if isinstance(part, dict)]


def build_mock_profile_intake_output(message: str) -> dict[str, Any]:
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

    return {
        "assistantMessage": (
            "I drafted profile updates from your message. Everything is private and needs review. "
            "Next, tell me about measurable outcomes or production constraints."
            if draft_facts or skill_claims or experience_and_projects
            else "I captured your target direction. Next, paste your resume or describe a shipped project so I can draft evidence-backed profile items."
        ),
        "targetRoleIntent": {
            **({"targetTitles": title} if title else {}),
            **({"targetRoleFamilies": "Applied AI, LLM systems, and forward-deployed engineering"} if mentions_ai else {}),
            **({"preferredWorkMode": "remote"} if "remote" in lower else {}),
            **({"preferredWorkMode": "hybrid"} if "hybrid" in lower else {}),
            **({"domainsOrIndustries": "developer tools"} if "developer tools" in lower else {}),
        },
        "draftFacts": draft_facts[:4],
        "skillClaims": skill_claims[:6],
        "experienceAndProjects": experience_and_projects[:3],
        "evidenceLinks": [generated_item({"url": url, "label": url, "source": source}) for url in links[:4]],
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
    }


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
