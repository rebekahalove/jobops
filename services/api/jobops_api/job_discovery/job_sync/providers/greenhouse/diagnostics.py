from __future__ import annotations

from dataclasses import dataclass


GREENHOUSE_DETAIL_REQUEST_PARAMS = {"questions": "true", "pay_transparency": "true"}


@dataclass
class GreenhouseDetailRequestStats:
    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped_by_guardrail: int = 0

    def to_json(self) -> dict[str, object]:
        return {
            "detailRequestsAttempted": self.attempted,
            "detailRequestsSucceeded": self.succeeded,
            "detailRequestsFailed": self.failed,
            "detailRequestsSkippedByGuardrail": self.skipped_by_guardrail,
        }


def greenhouse_detail_request(url: str) -> dict[str, object]:
    return {"url": url, "params": dict(GREENHOUSE_DETAIL_REQUEST_PARAMS)}


def safe_greenhouse_detail_error(error: Exception) -> dict[str, object]:
    detail: dict[str, object] = {
        "type": type(error).__name__,
        "message": "Greenhouse retrieve-job request failed.",
    }
    status = getattr(error, "code", None)
    if isinstance(status, int):
        detail["status"] = status
    return detail
