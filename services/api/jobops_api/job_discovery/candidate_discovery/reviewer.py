from __future__ import annotations

import json
import logging
from dataclasses import replace
from json import JSONDecodeError
from typing import Any

from ...model_connector import ModelConnector, ModelMessage, ModelRequest
from ...settings import Settings
from ..models import JobDiscoveryRequest
from .models import JobPoolEntry, JobReviewResult, RejectedJobDecision, SelectedJobDecision
from .prompts import JOB_REVIEW_SELECTOR_SYSTEM_PROMPT
from .rejection_reasons import REJECTION_REASON_CODES, normalize_reason_codes


logger = logging.getLogger(__name__)
DEBUG_RESPONSE_PREVIEW_CHARS = 6000
DEBUG_RESPONSE_TAIL_CHARS = 2000
REVIEW_MAX_OUTPUT_TOKENS = 32000


class JobReviewSelector:
    def review(
        self,
        request: JobDiscoveryRequest,
        *,
        connector: ModelConnector | None,
        settings: Settings,
        job_pool: list[JobPoolEntry],
        max_selected: int,
    ) -> JobReviewResult:
        bounded_pool = job_pool[: max(1, min(len(job_pool), settings.job_discovery_candidate_pool_limit or 80))]
        model_request = self.build_model_request(request, job_pool=bounded_pool, max_selected=max_selected)
        if connector is not None:
            try:
                response = connector.generate(model_request)
            except Exception as exc:
                return safe_review_unavailable(
                    bounded_pool,
                    reason=f"connector_error:{exc.__class__.__name__}",
                    diagnostics={"modelReviewAttemptCount": 1, "modelReviewErrorType": exc.__class__.__name__},
                )
            try:
                parsed = parse_review_response(response.text)
                return replace(parsed, diagnostics={**parsed.diagnostics, "modelReviewCompleted": True, "modelReviewAttemptCount": 1})
            except (JSONDecodeError, ValueError) as first_error:
                first_finish_reason = getattr(response, "finish_reason", None)
                log_invalid_review_response(
                    settings,
                    attempt=1,
                    error=first_error,
                    response_text=response.text,
                    finish_reason=first_finish_reason,
                )
                retry_request = self.build_retry_request(model_request, response_text=response.text)
                retry_response_text = ""
                retry_finish_reason = None
                try:
                    retry_response = connector.generate(retry_request)
                    retry_response_text = retry_response.text
                    retry_finish_reason = getattr(retry_response, "finish_reason", None)
                    parsed = parse_review_response(retry_response_text)
                    return replace(parsed, diagnostics={**parsed.diagnostics, "modelReviewCompleted": True, "modelReviewAttemptCount": 2, "modelReviewRetried": True})
                except Exception as retry_error:
                    log_invalid_review_response(
                        settings,
                        attempt=2,
                        error=retry_error,
                        response_text=retry_response_text,
                        finish_reason=retry_finish_reason,
                    )
                    debug_diagnostics = invalid_review_response_debug(
                        settings,
                        attempt=2,
                        error=retry_error,
                        response_text=retry_response_text or response.text,
                        finish_reason=retry_finish_reason or first_finish_reason,
                    )
                    return safe_review_unavailable(
                        bounded_pool,
                        reason=f"model_review_invalid_json:{retry_error.__class__.__name__}",
                        diagnostics={
                            "modelReviewAttemptCount": 2,
                            "modelReviewRetried": True,
                            "modelReviewErrorType": retry_error.__class__.__name__,
                            "modelReviewFirstErrorType": first_error.__class__.__name__,
                            "modelReviewFirstFinishReason": first_finish_reason,
                            **debug_diagnostics,
                        },
                    )
            except Exception as exc:
                return safe_review_unavailable(
                    bounded_pool,
                    reason=f"model_review_parse_error:{exc.__class__.__name__}",
                    diagnostics={"modelReviewAttemptCount": 1, "modelReviewErrorType": exc.__class__.__name__},
                )
        return safe_review_unavailable(bounded_pool, reason="connector_unavailable", diagnostics={"modelReviewAttemptCount": 0})

    def build_model_request(
        self,
        request: JobDiscoveryRequest,
        *,
        job_pool: list[JobPoolEntry],
        max_selected: int,
    ) -> ModelRequest:
        payload = {
            "latestUserMessage": request.latest_user_message,
            "maxSelectedJobs": max_selected,
            "allowedRejectionReasonCodes": sorted(REJECTION_REASON_CODES),
            "jobPool": [entry.__dict__ for entry in job_pool],
            "outputRules": [
                "selectedJobs must contain at most maxSelectedJobs entries.",
                "Keep rationales and explanations concise.",
            ],
            "outputSchema": {
                "userVisibleSummary": "string",
                "selectedJobs": [{"jobListingId": "string", "rationale": "string", "matchHighlights": ["string"]}],
                "rejectedJobs": [{"jobListingId": "string", "reasonCodes": ["location"], "explanation": "string"}],
                "criteriaAdjustmentSuggestion": {"shouldAskUser": False, "message": None, "criteriaToRelax": []},
            },
        }
        return ModelRequest(
            task="candidate_job_review",
            temperature=0.1,
            max_output_tokens=REVIEW_MAX_OUTPUT_TOKENS,
            response_mime_type="application/json",
            search_grounding=False,
            metadata={"feature": "candidate_job_review", "job_pool_count": len(job_pool)},
            messages=[
                ModelMessage(role="system", content=JOB_REVIEW_SELECTOR_SYSTEM_PROMPT),
                ModelMessage(role="user", content=json.dumps(payload, sort_keys=True, default=str)),
            ],
        )

    def build_retry_request(self, request: ModelRequest, *, response_text: str) -> ModelRequest:
        return replace(
            request,
            temperature=0,
            max_output_tokens=max(request.max_output_tokens, REVIEW_MAX_OUTPUT_TOKENS),
            messages=[
                *request.messages,
                ModelMessage(
                    role="user",
                    content=(
                        "The previous review response could not be parsed as valid JSON. Return exactly one valid "
                        "JSON object using the requested output schema. Do not include markdown, code fences, prose, "
                        "comments, or trailing commas. If no jobs should be selected, return empty selectedJobs and "
                        "rejectedJobs arrays with a userVisibleSummary. Respect maxSelectedJobs."
                    ),
                ),
            ],
            metadata={**request.metadata, "retryForInvalidJson": True, "previousResponsePreviewLength": min(len(response_text), 500)},
        )


def safe_review_unavailable(job_pool: list[JobPoolEntry], *, reason: str, diagnostics: dict[str, Any] | None = None) -> JobReviewResult:
    if job_pool:
        summary = "I found synced jobs to review, but model review did not complete, so I did not add jobs to your list."
    else:
        summary = "I did not find synced jobs that matched this request yet."
    return JobReviewResult(
        user_visible_summary=summary,
        selected_jobs=(),
        rejected_jobs=(),
        diagnostics={
            "modelReviewCompleted": False,
            "modelReviewFallback": True,
            "modelReviewFailureReason": reason,
            "jobPoolCount": len(job_pool),
            **(diagnostics or {}),
        },
    )


def log_invalid_review_response(
    settings: Settings,
    *,
    attempt: int,
    error: BaseException,
    response_text: str,
    finish_reason: str | None,
) -> None:
    if settings.app_env.strip().lower() == "prod":
        return
    preview = response_text[:DEBUG_RESPONSE_PREVIEW_CHARS]
    tail = response_text[-DEBUG_RESPONSE_TAIL_CHARS:] if len(response_text) > DEBUG_RESPONSE_PREVIEW_CHARS else ""
    logger.warning(
        "Candidate job review returned invalid JSON: %s",
        json.dumps(
            {
                "attempt": attempt,
                "errorType": error.__class__.__name__,
                "error": str(error),
                "finishReason": finish_reason,
                "responseLength": len(response_text),
                "responsePreview": preview,
                "responseTail": tail,
            },
            sort_keys=True,
        ),
    )


def invalid_review_response_debug(
    settings: Settings,
    *,
    attempt: int,
    error: BaseException,
    response_text: str,
    finish_reason: str | None,
) -> dict[str, Any]:
    if settings.app_env.strip().lower() == "prod":
        return {}
    preview = response_text[:DEBUG_RESPONSE_PREVIEW_CHARS]
    tail = response_text[-DEBUG_RESPONSE_TAIL_CHARS:] if len(response_text) > DEBUG_RESPONSE_PREVIEW_CHARS else ""
    return {
        "debugInvalidReviewAttempt": attempt,
        "debugInvalidReviewErrorType": error.__class__.__name__,
        "debugInvalidReviewError": str(error),
        "debugInvalidReviewFinishReason": finish_reason,
        "debugInvalidReviewResponseLength": len(response_text),
        "debugInvalidReviewResponsePreview": preview,
        "debugInvalidReviewResponseTail": tail,
    }


def validate_review_result(review: JobReviewResult, reviewed_job_listing_ids: tuple[str, ...]) -> JobReviewResult:
    reviewed_ids = set(reviewed_job_listing_ids)
    selected: list[SelectedJobDecision] = []
    selected_ids: set[str] = set()
    rejected_by_id: dict[str, RejectedJobDecision] = {}
    invalid_selected_ids: list[str] = []
    invalid_rejected_ids: list[str] = []
    duplicate_decision_count = 0
    selected_wins_conflict_count = 0

    for decision in review.selected_jobs:
        job_listing_id = decision.job_listing_id
        if job_listing_id not in reviewed_ids:
            invalid_selected_ids.append(job_listing_id)
            continue
        if job_listing_id in selected_ids:
            duplicate_decision_count += 1
            continue
        selected.append(decision)
        selected_ids.add(job_listing_id)

    for decision in review.rejected_jobs:
        job_listing_id = decision.job_listing_id
        if job_listing_id not in reviewed_ids:
            invalid_rejected_ids.append(job_listing_id)
            continue
        if job_listing_id in selected_ids:
            selected_wins_conflict_count += 1
            continue
        normalized = RejectedJobDecision(
            job_listing_id=job_listing_id,
            reason_codes=tuple(normalize_reason_codes(decision.reason_codes)),
            explanation=decision.explanation,
        )
        existing = rejected_by_id.get(job_listing_id)
        if existing is not None:
            duplicate_decision_count += 1
            rejected_by_id[job_listing_id] = RejectedJobDecision(
                job_listing_id=job_listing_id,
                reason_codes=tuple(normalize_reason_codes((*existing.reason_codes, *normalized.reason_codes))),
                explanation=existing.explanation or normalized.explanation,
            )
            continue
        rejected_by_id[job_listing_id] = normalized

    validation_diagnostics = {
        "invalidSelectedJobIds": invalid_selected_ids,
        "invalidRejectedJobIds": invalid_rejected_ids,
        "duplicateDecisionCount": duplicate_decision_count,
        "selectedWinsConflictCount": selected_wins_conflict_count,
    }
    return replace(
        review,
        selected_jobs=tuple(selected),
        rejected_jobs=tuple(rejected_by_id.values()),
        diagnostics={**review.diagnostics, "reviewValidation": validation_diagnostics},
    )


def parse_review_response(raw_text: str) -> JobReviewResult:
    parsed = json.loads(extract_first_json(raw_text))
    selected = tuple(
        SelectedJobDecision(
            job_listing_id=str(item.get("jobListingId") or item.get("job_listing_id")),
            rationale=item.get("rationale"),
            match_highlights=tuple(item.get("matchHighlights") or item.get("match_highlights") or ()),
        )
        for item in parsed.get("selectedJobs", [])
        if item.get("jobListingId") or item.get("job_listing_id")
    )
    rejected = tuple(
        RejectedJobDecision(
            job_listing_id=str(item.get("jobListingId") or item.get("job_listing_id")),
            reason_codes=tuple(normalize_reason_codes(item.get("reasonCodes") or item.get("reason_codes") or ["other"])),
            explanation=item.get("explanation"),
        )
        for item in parsed.get("rejectedJobs", [])
        if item.get("jobListingId") or item.get("job_listing_id")
    )
    return JobReviewResult(
        user_visible_summary=str(parsed.get("userVisibleSummary") or "I reviewed synced jobs."),
        selected_jobs=selected,
        rejected_jobs=rejected,
        criteria_adjustment_suggestion=parsed.get("criteriaAdjustmentSuggestion") or {},
        diagnostics={"modelReviewCompleted": True},
    )


def extract_first_json(raw_text: str) -> str:
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Model response did not include a JSON object.")
    return raw_text[start : end + 1]
