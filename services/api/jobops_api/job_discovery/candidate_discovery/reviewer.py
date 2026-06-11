from __future__ import annotations

import json
from typing import Any

from ...model_connector import ModelConnector, ModelMessage, ModelRequest
from ...settings import Settings
from ..models import JobDiscoveryRequest
from .models import JobPoolEntry, JobReviewResult, RejectedJobDecision, SelectedJobDecision
from .prompts import JOB_REVIEW_SELECTOR_SYSTEM_PROMPT
from .rejection_reasons import REJECTION_REASON_CODES, normalize_reason_codes


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
                return parse_review_response(response.text)
            except Exception:
                pass
        return deterministic_review(bounded_pool, max_selected=max_selected)

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
            max_output_tokens=6000,
            response_mime_type="application/json",
            search_grounding=False,
            metadata={"feature": "candidate_job_review", "job_pool_count": len(job_pool)},
            messages=[
                ModelMessage(role="system", content=JOB_REVIEW_SELECTOR_SYSTEM_PROMPT),
                ModelMessage(role="user", content=json.dumps(payload, sort_keys=True, default=str)),
            ],
        )


def deterministic_review(job_pool: list[JobPoolEntry], *, max_selected: int) -> JobReviewResult:
    selected_entries = job_pool[: max(0, max_selected)]
    rejected_entries = job_pool[max(0, max_selected) :]
    selected = tuple(
        SelectedJobDecision(
            job_listing_id=entry.job_listing_id,
            rationale=f"{entry.title} at {entry.company_name} matched the synced-job search.",
            match_highlights=tuple(value for value in (entry.location_display, entry.remote_work_mode) if value),
        )
        for entry in selected_entries
    )
    rejected = tuple(
        RejectedJobDecision(
            job_listing_id=entry.job_listing_id,
            reason_codes=("other",),
            explanation="Not selected in this bounded model review batch.",
        )
        for entry in rejected_entries
    )
    if selected:
        summary = f"I found {len(job_pool)} synced jobs, reviewed {len(job_pool)}, and added {len(selected)} to your jobs list."
    elif job_pool:
        summary = f"I found {len(job_pool)} jobs to review, but did not add any."
    else:
        summary = "I did not find synced jobs that matched this request yet."
    return JobReviewResult(user_visible_summary=summary, selected_jobs=selected, rejected_jobs=rejected)


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
    )


def extract_first_json(raw_text: str) -> str:
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Model response did not include a JSON object.")
    return raw_text[start : end + 1]
