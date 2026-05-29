from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal


ModelTask = Literal[
    "command_router",
    "company_discovery",
    "job_candidate_selection",
    "job_discovery",
    "command_center_guidance",
    "profile_extract",
    "profile_draft_update",
    "intake_followup",
    "public_candidate_qa",
    "role_fit",
    "bulk_triage",
    "eval_harness",
    "judge_or_second_pass",
]


@dataclass(frozen=True)
class ModelMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class ModelRequest:
    task: ModelTask
    messages: list[ModelMessage]
    model: str | None = None
    temperature: float = 0
    max_output_tokens: int = 4000
    response_mime_type: str | None = None
    thinking_budget: int | None = None
    search_grounding: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def with_model(self, model: str) -> ModelRequest:
        return replace(self, model=model)


@dataclass(frozen=True)
class ModelUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class ModelResponse:
    text: str
    provider: str
    model: str
    finish_reason: str | None = None
    usage: ModelUsage | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
