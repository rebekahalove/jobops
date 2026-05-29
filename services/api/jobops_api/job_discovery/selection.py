from __future__ import annotations

import json
import logging
from dataclasses import replace
from typing import Any

from pydantic import ValidationError

from ..company_discovery import (
    add_truncation_hint,
    extract_first_json_object,
    format_validation_issues,
    model_request_debug_fields,
    model_response_debug_fields,
    preview_model_response,
    safe_error_detail_fields,
    validation_issues_indicate_truncation,
)
from ..model_connector import (
    ModelConfigurationError,
    ModelConnector,
    ModelMessage,
    ModelProviderError,
    ModelRequest,
    create_model_connector,
    read_model_connector_config_from_settings,
    route_model_request,
)
from ..settings import Settings
from .models import (
    CandidatePoolEntry,
    JobCandidateSelectionItem,
    JobCandidateSelectionOutput,
    JobCandidateSelectionResult,
    JobDiscoveryRequest,
    JobDiscoveryServiceResult,
    LiveJobSourceResult,
    ProviderDiagnostic,
)
from .provider_utils import safe_log_preview


logger = logging.getLogger(__name__)
MODEL_RESPONSE_LOG_PREVIEW_CHARS = 1200


class JobCandidateSelectionValidationFailure(Exception):
    def __init__(self, issues: list[str]) -> None:
        super().__init__("Job candidate selection output validation failed.")
        self.issues = issues


def select_job_candidates_with_model(
    request: JobDiscoveryRequest,
    *,
    connector: ModelConnector | None,
    settings: Settings,
    candidate_entries: list[CandidatePoolEntry],
    current_saved_jobs: list[dict[str, Any]],
    current_saved_companies: list[dict[str, Any]],
    target_context: dict[str, Any],
    private_profile_context: dict[str, Any],
    provider_diagnostics: list[ProviderDiagnostic],
    user_constraints: list[str],
    save_limit: int,
) -> JobCandidateSelectionResult | JobDiscoveryServiceResult:
    model_request = build_job_candidate_selection_model_request(
        request,
        candidate_entries=candidate_entries,
        current_saved_jobs=current_saved_jobs,
        current_saved_companies=current_saved_companies,
        target_context=target_context,
        private_profile_context=private_profile_context,
        provider_diagnostics=provider_diagnostics,
        user_constraints=user_constraints,
        save_limit=save_limit,
    )
    connector_config = read_model_connector_config_from_settings(settings)
    routed_request = route_model_request(model_request, connector_config.routing)
    try:
        active_connector = connector or create_model_connector(
            connector_config,
            mock_responses_by_task={"job_candidate_selection": build_mock_job_candidate_selection_response},
        )
    except ModelConfigurationError as error:
        return JobDiscoveryServiceResult(
            body={
                "ok": False,
                "error": "Job candidate selection model is not configured. No jobs were saved.",
                "code": error.code,
                **safe_error_detail_fields(settings, error),
                **model_request_debug_fields(settings, routed_request),
            },
            status_code=503,
        )
    try:
        response = active_connector.generate(routed_request)
    except ModelProviderError as error:
        return JobDiscoveryServiceResult(
            body={
                "ok": False,
                "error": "Job candidate selection model call failed. No jobs were saved.",
                "code": error.code,
                **model_request_debug_fields(settings, routed_request),
            },
            status_code=502,
        )

    try:
        output = validate_job_candidate_selection_output(response.text)
    except JobCandidateSelectionValidationFailure as error:
        first_issues = add_truncation_hint(error.issues, response.finish_reason)
        failure_payload = {
            "provider": response.provider,
            "model": response.model,
            "finishReason": response.finish_reason,
            "validationIssues": first_issues[:8],
            "responsePreview": preview_model_response(response.text)[:MODEL_RESPONSE_LOG_PREVIEW_CHARS],
        }
        logger.warning(
            "Job candidate selection model output validation failed: %s",
            json.dumps(failure_payload, sort_keys=True, default=str),
        )
        if validation_issues_indicate_truncation(first_issues):
            retry_request = build_compact_job_candidate_selection_retry_request(routed_request)
            try:
                response = active_connector.generate(retry_request)
                output = validate_job_candidate_selection_output(response.text)
                routed_request = retry_request
            except ModelProviderError as retry_error:
                return JobDiscoveryServiceResult(
                    body={
                        "ok": False,
                        "error": "Job candidate selection model retry failed after truncation. No jobs were saved.",
                        "code": retry_error.code,
                        **model_request_debug_fields(settings, retry_request),
                    },
                    status_code=502,
                )
            except JobCandidateSelectionValidationFailure as retry_validation_error:
                retry_issues = add_truncation_hint(retry_validation_error.issues, response.finish_reason)
                logger.warning(
                    "Job candidate selection compact retry validation failed: %s",
                    json.dumps(
                        {
                            "provider": response.provider,
                            "model": response.model,
                            "finishReason": response.finish_reason,
                            "validationIssues": retry_issues[:8],
                            "responsePreview": preview_model_response(response.text)[:MODEL_RESPONSE_LOG_PREVIEW_CHARS],
                        },
                        sort_keys=True,
                        default=str,
                    ),
                )
                return JobDiscoveryServiceResult(
                    body={
                        "ok": False,
                        "error": (
                            "Job candidate selection model response was truncated before valid JSON completed. "
                            "No jobs were saved."
                            if validation_issues_indicate_truncation(retry_issues)
                            else "Job candidate selection model returned invalid JSON. No jobs were saved."
                        ),
                        "code": (
                            "job_candidate_selection_truncated"
                            if validation_issues_indicate_truncation(retry_issues)
                            else "job_candidate_selection_validation_failed"
                        ),
                        "validationIssues": retry_issues[:8],
                        **model_request_debug_fields(settings, retry_request),
                        **model_response_debug_fields(settings, response),
                    },
                    status_code=502,
                )
        else:
            return JobDiscoveryServiceResult(
                body={
                    "ok": False,
                    "error": "Job candidate selection model returned invalid JSON. No jobs were saved.",
                    "code": "job_candidate_selection_validation_failed",
                    "validationIssues": first_issues[:8],
                    **model_request_debug_fields(settings, routed_request),
                    **model_response_debug_fields(settings, response),
                },
                status_code=502,
            )

    candidate_map = {entry.candidate_id: entry for entry in candidate_entries}
    selected_entries: list[CandidatePoolEntry] = []
    invalid_candidate_ids: list[str] = []
    seen_ids: set[str] = set()
    for selection in sorted(output.selected_jobs, key=lambda item: item.rank or 999):
        candidate_id = selection.candidate_id.strip()
        if candidate_id in seen_ids:
            continue
        seen_ids.add(candidate_id)
        entry = candidate_map.get(candidate_id)
        if entry is None:
            invalid_candidate_ids.append(candidate_id)
            continue
        selected_entries.append(entry)
        if len(selected_entries) >= save_limit:
            break
    if invalid_candidate_ids:
        logger.warning(
            "Job candidate selection returned unknown candidate IDs: %s",
            json.dumps({"invalidCandidateIds": invalid_candidate_ids[:10]}, sort_keys=True),
        )
    return JobCandidateSelectionResult(
        output=output,
        selected_entries=selected_entries,
        invalid_candidate_ids=invalid_candidate_ids,
        response_provider=response.provider,
        response_model=response.model,
        request=routed_request,
        response=response,
    )


def build_empty_job_candidate_selection_result(settings: Settings) -> JobCandidateSelectionResult:
    request = ModelRequest(task="job_candidate_selection", messages=[], model=settings.default_model)
    return JobCandidateSelectionResult(
        output=JobCandidateSelectionOutput(
            assistantMessage="No live provider candidates were available for model selection, so no jobs were saved."
        ),
        selected_entries=[],
        invalid_candidate_ids=[],
        response_provider="none",
        response_model="none",
        request=request,
        response=None,
    )


def selected_selection_pairs(
    selection_result: JobCandidateSelectionResult,
) -> list[tuple[CandidatePoolEntry, JobCandidateSelectionItem]]:
    selections = {selection.candidate_id: selection for selection in selection_result.output.selected_jobs}
    return [(entry, selections[entry.candidate_id]) for entry in selection_result.selected_entries if entry.candidate_id in selections]


def apply_model_selection_to_source_result(
    result: LiveJobSourceResult,
    selection: JobCandidateSelectionItem,
) -> LiveJobSourceResult:
    fit_summary = selection.fit_summary or selection.selection_reason
    return replace(result, fit_summary=fit_summary)


def build_job_candidate_selection_model_request(
    request: JobDiscoveryRequest,
    *,
    candidate_entries: list[CandidatePoolEntry],
    current_saved_jobs: list[dict[str, Any]],
    current_saved_companies: list[dict[str, Any]],
    target_context: dict[str, Any],
    private_profile_context: dict[str, Any],
    provider_diagnostics: list[ProviderDiagnostic],
    user_constraints: list[str],
    save_limit: int,
) -> ModelRequest:
    payload = {
        "latest_user_message": request.latest_user_message,
        "active_workspace": request.active_workspace,
        "client_context": compact_client_context(request.client_context),
        "save_limit": save_limit,
        "candidate_target_context": target_context,
        "private_profile_context": private_profile_context,
        "current_saved_jobs": current_saved_jobs[:50],
        "current_saved_companies": current_saved_companies[:50],
        "user_constraints": user_constraints,
        "provider_diagnostics": [diagnostic.to_dict() for diagnostic in provider_diagnostics],
        "candidate_jobs": [serialize_candidate_pool_entry(entry) for entry in candidate_entries],
        "selection_rules": {
            "select_by_candidate_id_only": True,
            "do_not_introduce_job_facts": True,
            "max_selected_jobs": save_limit,
            "provider_facts_are_source_of_truth": True,
        },
    }
    return ModelRequest(
        task="job_candidate_selection",
        temperature=0.1,
        max_output_tokens=16000,
        response_mime_type="application/json",
        search_grounding=False,
        metadata={
            "feature": "job_candidate_selection",
            "candidate_count": len(candidate_entries),
            "save_limit": save_limit,
        },
        messages=[
            ModelMessage(role="system", content=JOB_CANDIDATE_SELECTION_SYSTEM_PROMPT),
            ModelMessage(role="user", content=json.dumps(payload, sort_keys=True, default=str)),
        ],
    )


JOB_CANDIDATE_SELECTION_SYSTEM_PROMPT = """You are the JobOps Job Candidate Selection Agent.

You select the best jobs from provider-backed candidate jobs. The provider data is the only source of truth for job title, company, URL, posting date, provider, and source metadata.

Rules:
- Return JSON only.
- Select jobs only by candidateId from the provided candidate_jobs list.
- Do not invent or modify job titles, companies, URLs, posting dates, salaries, locations, or provider facts.
- If a candidate is weak, duplicate, excluded by the user's constraints, or a poor role fit, do not select it.
- Prioritize roles that directly match the user's stated command, saved target roles, profile headline, skills, experience, preferences, and constraints.
- Prefer candidates where the role responsibilities, industry, seniority, location, work mode, and employment type match the supplied profile and target context.
- Treat domain-specific interests from the profile as user-specific signals, not universal product defaults.
- Honor the user's explicit exclusions and constraints exactly as supplied. If uncertain about an excluded category, skip.
- Do not overvalue generic roles unless they clearly match the user's stated role targets or profile context.
- Distinguish an interesting company from a good role fit.
- Return at most save_limit selected jobs.
- Keep assistantMessage under 60 words.
- Keep fitSummary under 140 characters.
- Keep selectionReason under 100 characters.
- concerns must be [] unless a short concern is essential.
- skippedCandidateNotes may be [] and should include at most 5 items.

Return exactly this JSON shape:
{
  "assistantMessage": "Concise markdown summary.",
  "selectedJobs": [
    {
      "candidateId": "J001",
      "fitSummary": "Why this provider-backed candidate is a strong fit.",
      "rank": 1,
      "selectionReason": "Short grounded reason.",
      "concerns": []
    }
  ],
  "skippedCandidateNotes": [
    {
      "candidateId": "J002",
      "reason": "Weak role fit or excluded industry."
    }
  ],
  "clarifyingQuestions": []
}"""


COMPACT_JOB_CANDIDATE_SELECTION_RETRY_INSTRUCTIONS = """

Compact retry rules because the previous selection response was truncated:
- Return valid JSON only.
- Do not include markdown fences or text outside JSON.
- selectedJobs must contain only candidateId, fitSummary, rank, selectionReason, concerns.
- fitSummary max 90 characters.
- selectionReason max 70 characters.
- concerns must be [].
- skippedCandidateNotes must be [].
- assistantMessage max 25 words.
- Select at most save_limit candidate IDs from candidate_jobs.
"""


def build_compact_job_candidate_selection_retry_request(request: ModelRequest) -> ModelRequest:
    compact_messages: list[ModelMessage] = []
    for message in request.messages:
        if message.role == "system":
            compact_messages.append(
                ModelMessage(role="system", content=f"{message.content}{COMPACT_JOB_CANDIDATE_SELECTION_RETRY_INSTRUCTIONS}")
            )
        elif message.role == "user":
            compact_messages.append(ModelMessage(role="user", content=compact_job_candidate_selection_payload(message.content)))
        else:
            compact_messages.append(message)
    return replace(
        request,
        messages=compact_messages,
        max_output_tokens=max(request.max_output_tokens, 16000),
        metadata={**request.metadata, "compact_retry": True},
    )


def compact_job_candidate_selection_payload(raw_content: str) -> str:
    try:
        payload = json.loads(raw_content)
    except json.JSONDecodeError:
        return raw_content
    if not isinstance(payload, dict):
        return raw_content
    candidate_jobs = payload.get("candidate_jobs")
    if isinstance(candidate_jobs, list):
        payload["candidate_jobs"] = [
            compact_candidate_for_selection_retry(candidate)
            for candidate in candidate_jobs
            if isinstance(candidate, dict)
        ]
    payload["current_saved_jobs"] = compact_saved_job_urls(payload.get("current_saved_jobs"))
    payload["provider_diagnostics"] = compact_provider_diagnostics(payload.get("provider_diagnostics"))
    payload["compact_retry"] = True
    payload["output_constraints"] = {
        "assistantMessageMaxWords": 25,
        "fitSummaryMaxChars": 90,
        "selectionReasonMaxChars": 70,
        "skippedCandidateNotes": [],
    }
    return json.dumps(payload, sort_keys=True, default=str)


def compact_candidate_for_selection_retry(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidateId": candidate.get("candidateId"),
        "roughScore": candidate.get("roughScore"),
        "flags": candidate.get("flags"),
        "providerName": candidate.get("providerName"),
        "providerType": candidate.get("providerType"),
        "title": candidate.get("title"),
        "companyName": candidate.get("companyName"),
        "location": candidate.get("location"),
        "remoteWorkMode": candidate.get("remoteWorkMode"),
        "employmentType": candidate.get("employmentType"),
        "salaryText": candidate.get("salaryText"),
        "postingDate": candidate.get("postingDate"),
        "descriptionExcerpt": safe_log_preview(str(candidate.get("descriptionExcerpt") or ""), limit=180) or None,
    }


def compact_saved_job_urls(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in value[:50]:
        if not isinstance(item, dict):
            continue
        compact.append(
            {
                "title": item.get("title"),
                "company_name": item.get("company_name"),
                "normalized_url": item.get("normalized_url"),
            }
        )
    return compact


def compact_provider_diagnostics(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in value[:20]:
        if not isinstance(item, dict):
            continue
        compact.append(
            {
                "providerName": item.get("providerName"),
                "providerType": item.get("providerType"),
                "resultCount": item.get("resultCount"),
                "rawResultCount": item.get("rawResultCount"),
                "searchMode": item.get("searchMode"),
            }
        )
    return compact


def serialize_candidate_pool_entry(entry: CandidatePoolEntry) -> dict[str, Any]:
    result = entry.result
    return {
        "candidateId": entry.candidate_id,
        "roughScore": entry.rough_score,
        "flags": list(entry.flags),
        "providerName": result.source_provider,
        "providerType": result.provider_type,
        "sourceResultId": result.source_result_id,
        "title": result.title,
        "companyName": result.company_name,
        "location": result.location,
        "remoteWorkMode": result.remote_work_mode,
        "employmentType": result.employment_type,
        "salaryText": result.salary_text,
        "descriptionExcerpt": result.description_excerpt,
        "postingDate": result.posting_date.isoformat() if result.posting_date else None,
        "sourceUpdatedAt": result.source_updated_at.isoformat() if result.source_updated_at else None,
        "jobUrl": result.job_url,
        "applyUrl": result.apply_url,
        "sourceQuery": result.source_query,
        "atsProvider": result.ats_provider,
        "atsBoardToken": result.ats_board_token,
    }


def validate_job_candidate_selection_output(raw_text: str) -> JobCandidateSelectionOutput:
    try:
        parsed = parse_selection_json(raw_text)
        return JobCandidateSelectionOutput.model_validate(parsed)
    except (json.JSONDecodeError, ValueError, ValidationError) as error:
        issues = [str(error)]
        if isinstance(error, ValidationError):
            issues = format_validation_issues(error)
        raise JobCandidateSelectionValidationFailure(issues) from error


def parse_selection_json(raw_text: str) -> Any:
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        extracted = extract_first_json_object(raw_text)
        if extracted is None:
            raise
        return json.loads(extracted)


def compact_client_context(client_context: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(client_context, dict):
        return {}
    transcript = client_context.get("transcript")
    if not isinstance(transcript, dict):
        return {}
    raw_messages = transcript.get("messages")
    if not isinstance(raw_messages, list):
        return {}
    messages = []
    for message in raw_messages[-8:]:
        if not isinstance(message, dict):
            continue
        text = str(message.get("text") or "").strip()
        if not text:
            continue
        messages.append(
            {
                "role": message.get("role"),
                "type": message.get("type"),
                "text": text[:1000],
            }
        )
    return {"transcript": {"source": transcript.get("source"), "messages": messages}}


def build_mock_job_candidate_selection_response(request: ModelRequest) -> str:
    payload = json.loads(request.messages[-1].content) if request.messages else {}
    save_limit = int(payload.get("save_limit") or 5) if isinstance(payload, dict) else 5
    candidates = payload.get("candidate_jobs") if isinstance(payload, dict) else []
    if not isinstance(candidates, list):
        candidates = []
    selected = []
    for index, candidate in enumerate(candidates[:save_limit], start=1):
        if not isinstance(candidate, dict):
            continue
        selected.append(
            {
                "candidateId": candidate.get("candidateId"),
                "fitSummary": "Strong provider-backed match for the current job search.",
                "rank": index,
                "selectionReason": "Mock selector chose the highest-ranked rough candidate.",
                "concerns": [],
            }
        )
    return json.dumps(
        {
            "assistantMessage": f"Selected {len(selected)} provider-backed job candidate(s) to save.",
            "selectedJobs": selected,
            "skippedCandidateNotes": [],
            "clarifyingQuestions": [],
        }
    )
