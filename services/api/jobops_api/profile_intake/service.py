from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from ..settings import Settings, load_settings
from .artifacts import (
    build_profile_intake_input_metrics,
    build_run_metadata,
    create_profile_intake_artifact_run,
)
from .models import ProfileIntakeExtractRequest, ProfileIntakeOutput, SAFE_VALIDATION_ERROR
from .prompt import (
    PROFILE_INTAKE_SCHEMA_NAME,
    build_profile_intake_user_prompt,
    build_prompt_artifact,
    build_request_metadata,
    PROFILE_INTAKE_SYSTEM_PROMPT,
)
from .providers import (
    ModelConfigurationError,
    ModelProviderError,
    ProfileIntakeProvider,
    build_model_request,
    create_profile_intake_provider,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProfileIntakeServiceResult:
    body: dict[str, Any]
    status_code: int


def run_profile_intake_extraction(
    request: ProfileIntakeExtractRequest,
    *,
    provider: ProfileIntakeProvider | None = None,
    settings: Settings | None = None,
) -> ProfileIntakeServiceResult:
    active_settings = settings or load_settings()
    input_metrics = build_profile_intake_input_metrics(request.latest_user_message, request.existing_draft)
    system_prompt = PROFILE_INTAKE_SYSTEM_PROMPT
    user_prompt = build_profile_intake_user_prompt(request)
    model_request = build_model_request(
        request,
        model=active_settings.default_model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )
    artifact_run = create_profile_intake_artifact_run(active_settings)

    artifact_run.write_json(
        "request-metadata.json",
        build_request_metadata(
            input_metrics=input_metrics.to_json(),
            max_output_tokens=model_request.max_output_tokens,
            model=model_request.model,
            task=model_request.task,
            temperature=model_request.temperature,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        ),
    )
    artifact_run.write_raw_text("prompt.txt", build_prompt_artifact(system_prompt, user_prompt))

    try:
        active_provider = provider or create_profile_intake_provider(active_settings)
    except ModelConfigurationError as error:
        _write_failure_metadata(
            artifact_run=artifact_run,
            input_metrics=input_metrics,
            issues=[str(error)],
            latency_ms=0,
            model_request=model_request,
            response=None,
            validation_issue_count=0,
        )
        return ProfileIntakeServiceResult(
            body={
                "ok": False,
                "error": (
                    "Profile intake model is not configured. Set JOBOPS_LLM_PROVIDER=mock for deterministic local "
                    "mode, or configure JOBOPS_LLM_PROVIDER=gemini with server-side GEMINI_API_KEY."
                ),
                "code": error.code,
                **debug_fields(artifact_run),
            },
            status_code=503,
        )

    started_at = time.perf_counter()
    response = None
    try:
        response = active_provider.generate(model_request)
        latency_ms = round((time.perf_counter() - started_at) * 1000)
    except ModelProviderError as error:
        latency_ms = round((time.perf_counter() - started_at) * 1000)
        _write_failure_metadata(
            artifact_run=artifact_run,
            input_metrics=input_metrics,
            issues=[str(error)],
            latency_ms=latency_ms,
            model_request=model_request,
            response=None,
            validation_issue_count=0,
        )
        logger.warning(
            "[profile_intake] provider call failed",
            extra={
                "artifact_path": artifact_run.artifact_path,
                "feature": "profile_intake",
                "run_id": artifact_run.run_id,
            },
        )
        return ProfileIntakeServiceResult(
            body={
                "ok": False,
                "error": "Profile intake model call failed. No draft data was applied.",
                "code": error.code,
                **debug_fields(artifact_run),
            },
            status_code=502,
        )

    artifact_run.write_raw_text("raw-response.txt", response.text)

    try:
        parsed = parse_profile_intake_json(response.text)
        output = ProfileIntakeOutput.model_validate(parsed)
    except ProfileIntakeValidationFailure as error:
        issues = add_truncation_hint(error.issues, response.finish_reason)
        return validation_failure_result(
            artifact_run=artifact_run,
            input_metrics=input_metrics,
            issues=issues,
            latency_ms=latency_ms,
            model_request=model_request,
            response=response,
        )
    except ValidationError as error:
        issues = add_truncation_hint(format_validation_issues(error), response.finish_reason)
        return validation_failure_result(
            artifact_run=artifact_run,
            input_metrics=input_metrics,
            issues=issues,
            latency_ms=latency_ms,
            model_request=model_request,
            response=response,
        )

    output_json = output.model_dump(by_alias=True, exclude_none=True)
    if artifact_run.enabled and artifact_run.run_id:
        artifact_run.write_json("parsed-output.json", output_json)
        artifact_run.write_json(
            "metadata.json",
            build_run_metadata(
                input_metrics=input_metrics,
                latency_ms=latency_ms,
                request=model_request,
                response=response,
                run_id=artifact_run.run_id,
                status="success",
                validation_issue_count=0,
            ),
        )

    return ProfileIntakeServiceResult(
        body={
            "ok": True,
            "result": output_json,
        },
        status_code=200,
    )


class ProfileIntakeValidationFailure(Exception):
    def __init__(self, issues: list[str]) -> None:
        super().__init__("Profile intake output validation failed.")
        self.issues = issues


def parse_profile_intake_json(raw_text: str) -> Any:
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

    raise ProfileIntakeValidationFailure(["Output is not valid JSON."])


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


def validation_failure_result(
    *,
    artifact_run,
    input_metrics,
    issues: list[str],
    latency_ms: int,
    model_request,
    response,
) -> ProfileIntakeServiceResult:
    if artifact_run.enabled and artifact_run.run_id:
        artifact_run.write_json(
            "validation-error.json",
            {
                "feature": "profile_intake",
                "issues": issues,
                "runId": artifact_run.run_id,
                "schemaName": PROFILE_INTAKE_SCHEMA_NAME,
                "validationIssueCount": len(issues),
            },
        )
        artifact_run.write_json(
            "metadata.json",
            build_run_metadata(
                input_metrics=input_metrics,
                latency_ms=latency_ms,
                request=model_request,
                response=response,
                run_id=artifact_run.run_id,
                status="failure",
                validation_issue_count=len(issues),
            ),
        )

    logger.warning(
        "[profile_intake] structured output validation failed run_id=%s provider=%s model=%s issues=%s artifact_path=%s",
        artifact_run.run_id,
        response.provider,
        response.model,
        issues,
        artifact_run.artifact_path,
    )

    return ProfileIntakeServiceResult(
        body={
            "ok": False,
            "error": SAFE_VALIDATION_ERROR,
            "issues": issues,
            **debug_fields(artifact_run),
        },
        status_code=502,
    )


def _write_failure_metadata(
    *,
    artifact_run,
    input_metrics,
    issues: list[str],
    latency_ms: int,
    model_request,
    response,
    validation_issue_count: int,
) -> None:
    if not artifact_run.enabled or not artifact_run.run_id:
        return

    artifact_run.write_json(
        "metadata.json",
        build_run_metadata(
            input_metrics=input_metrics,
            latency_ms=latency_ms,
            request=model_request,
            response=response,
            run_id=artifact_run.run_id,
            status="failure",
            validation_issue_count=validation_issue_count,
        ),
    )
    artifact_run.write_json(
        "validation-error.json",
        {
            "feature": "profile_intake",
            "issues": issues,
            "runId": artifact_run.run_id,
            "validationIssueCount": validation_issue_count,
        },
    )


def debug_fields(artifact_run) -> dict[str, str]:
    if not artifact_run.enabled:
        return {}

    return {
        **({"debug_run_id": artifact_run.run_id} if artifact_run.run_id else {}),
        **({"artifact_path": artifact_run.artifact_path} if artifact_run.artifact_path else {}),
    }


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

