from __future__ import annotations

from dataclasses import dataclass, field

from .models import ModelRequest, ModelTask


DEFAULT_MODEL_TASKS: set[ModelTask] = {
    "company_discovery",
    "job_candidate_selection",
    "command_center_guidance",
    "profile_extract",
    "profile_draft_update",
    "intake_followup",
    "application_materials_generation",
    "public_candidate_qa",
    "role_fit",
    "judge_or_second_pass",
}
CHEAP_MODEL_TASKS: set[ModelTask] = {
    "command_router",
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
