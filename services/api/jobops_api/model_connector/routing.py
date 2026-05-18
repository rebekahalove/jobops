from __future__ import annotations

from dataclasses import dataclass, field

from .models import ModelRequest, ModelTask


DEFAULT_MODEL_TASKS: set[ModelTask] = {
    "company_discovery",
    "profile_extract",
    "profile_draft_update",
    "intake_followup",
    "role_fit",
    "judge_or_second_pass",
}
CHEAP_MODEL_TASKS: set[ModelTask] = {
    "bulk_triage",
    "eval_harness",
}


@dataclass(frozen=True)
class ModelRoutingConfig:
    default_model: str
    cheap_model: str
    task_model_overrides: dict[ModelTask, str] = field(default_factory=dict)


def select_model_for_task(task: ModelTask, routing: ModelRoutingConfig) -> str:
    if task in routing.task_model_overrides:
        return routing.task_model_overrides[task]
    if task in CHEAP_MODEL_TASKS:
        return routing.cheap_model
    return routing.default_model


def route_model_request(request: ModelRequest, routing: ModelRoutingConfig) -> ModelRequest:
    if request.model:
        return request
    return request.with_model(select_model_for_task(request.task, routing))
