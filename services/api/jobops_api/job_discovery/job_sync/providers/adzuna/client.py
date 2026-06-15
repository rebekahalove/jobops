from __future__ import annotations

from ....provider_utils import fetch_json
from ...location_country import normalize_provider_country_code
from ...models import JobSyncRequest
from .models import AdzunaPageResult, AdzunaSearchRequest, AdzunaSearchResponse


ADZUNA_API_ROOT = "https://api.adzuna.com"


class AdzunaJobSyncClient:
    def __init__(self, *, app_id: str | None = None, app_key: str | None = None, results_per_page: int = 50) -> None:
        self.app_id = app_id
        self.app_key = app_key
        self.results_per_page = bounded_results_per_page(results_per_page)

    def search(self, request: JobSyncRequest) -> AdzunaSearchResponse:
        if not self.app_id or not self.app_key:
            raise ValueError("Adzuna Job Sync requires app_id and app_key.")
        provider_country = normalize_provider_country_code(request.provider_country)
        if not provider_country:
            raise ValueError("Adzuna Job Sync requests require provider_country.")
        max_pages = max(1, int(request.criteria_json.get("maxPages") or 1))
        results_per_page = bounded_results_per_page(int(request.criteria_json.get("resultsPerPage") or self.results_per_page))
        what_exclude = clean_optional_text(request.criteria_json.get("whatExclude"))

        pages: list[AdzunaPageResult] = []
        for page in range(1, max_pages + 1):
            page_request = AdzunaSearchRequest(
                provider_country=provider_country,
                api_path=f"/v1/api/jobs/{provider_country}/search/{page}",
                page=page,
                what=request.query_text or "",
                where=request.provider_where,
                what_exclude=what_exclude,
                results_per_page=results_per_page,
            )
            params: dict[str, object] = {
                "app_id": self.app_id,
                "app_key": self.app_key,
                "what": page_request.what,
                "results_per_page": page_request.results_per_page,
                "content-type": "application/json",
            }
            if page_request.where:
                params["where"] = page_request.where
            if page_request.what_exclude:
                params["what_exclude"] = page_request.what_exclude
            try:
                payload = fetch_json(f"{ADZUNA_API_ROOT}{page_request.api_path}", params=params)
            except Exception as error:
                pages.append(
                    AdzunaPageResult(
                        request=page_request,
                        results=(),
                        error=safe_page_error(error),
                    )
                )
                break
            results: tuple[object, ...] = ()
            provider_count: int | None = None
            provider_mean: float | None = None
            if isinstance(payload, dict):
                raw_results = payload.get("results")
                if isinstance(raw_results, list):
                    results = tuple(raw_results)
                provider_count = parse_int(payload.get("count"))
                provider_mean = parse_float(payload.get("mean"))
            pages.append(
                AdzunaPageResult(
                    request=page_request,
                    results=results,
                    provider_reported_count=provider_count,
                    provider_reported_mean=provider_mean,
                )
            )
        return AdzunaSearchResponse(pages=tuple(pages), requested_pages=max_pages)


def bounded_results_per_page(value: int) -> int:
    return max(1, min(value, 50))


def clean_optional_text(value: object) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(str(value).split()).strip()
    return cleaned or None


def parse_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def parse_float(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def safe_page_error(error: Exception) -> dict[str, object]:
    message = clean_optional_text(str(error)) or "Adzuna page request failed."
    detail: dict[str, object] = {"type": type(error).__name__, "message": message}
    status = getattr(error, "code", None)
    if isinstance(status, int):
        detail["status"] = status
    return detail
