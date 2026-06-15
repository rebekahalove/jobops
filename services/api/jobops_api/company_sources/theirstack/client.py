from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import TheirStackCompanySearchDiagnostics, TheirStackCompanySearchRequest, TheirStackCompanySearchResult


THEIRSTACK_COMPANY_SEARCH_URL = "https://api.theirstack.com/v1/companies/search"


class TheirStackCompanySearchError(RuntimeError):
    def __init__(self, message: str, *, diagnostics: TheirStackCompanySearchDiagnostics) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


HttpPost = Callable[[str, dict[str, str], bytes, float], tuple[int, dict[str, Any]]]


class TheirStackCompanySearchClient:
    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float = 20,
        http_post: HttpPost | None = None,
    ) -> None:
        cleaned_key = api_key.strip()
        if not cleaned_key:
            raise ValueError("TheirStack API key is required.")
        self._api_key = cleaned_key
        self._timeout_seconds = timeout_seconds
        self._http_post = http_post or default_http_post

    def search_companies(self, request: TheirStackCompanySearchRequest) -> TheirStackCompanySearchResult:
        requested_pages = max(1, request.max_pages)
        diagnostics = TheirStackCompanySearchDiagnostics(
            enabled=True,
            requested_pages=requested_pages,
            request_shape=request.sanitized_shape(),
        )
        companies: list[dict[str, Any]] = []
        total_companies: int | None = None
        fetched_pages = 0
        failed_pages = 0

        for page_offset in range(requested_pages):
            page = max(1, request.page) + page_offset
            body = request.to_api_body(page=page)
            encoded = json.dumps(body).encode("utf-8")
            headers = {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            try:
                status_code, payload = self._http_post(
                    THEIRSTACK_COMPANY_SEARCH_URL,
                    headers,
                    encoded,
                    self._timeout_seconds,
                )
            except TheirStackCompanySearchError:
                raise
            except Exception as exc:
                failed_pages += 1
                raise TheirStackCompanySearchError(
                    "TheirStack company search request failed.",
                    diagnostics=replace(
                        diagnostics,
                        fetched_pages=fetched_pages,
                        failed_pages=failed_pages,
                        error_type=exc.__class__.__name__,
                        error_message=str(exc),
                    ),
                ) from exc

            if status_code < 200 or status_code >= 300:
                failed_pages += 1
                raise TheirStackCompanySearchError(
                    f"TheirStack company search returned HTTP {status_code}.",
                    diagnostics=replace(
                        diagnostics,
                        fetched_pages=fetched_pages,
                        failed_pages=failed_pages,
                        error_type="http_error",
                        error_message=f"HTTP {status_code}",
                    ),
                )

            fetched_pages += 1
            page_companies = extract_companies(payload)
            companies.extend(page_companies)
            total_companies = total_companies if total_companies is not None else extract_total_companies(payload)
            if not page_companies:
                break

        final_diagnostics = replace(
            diagnostics,
            fetched_pages=fetched_pages,
            failed_pages=failed_pages,
            skipped_pages=max(0, requested_pages - fetched_pages - failed_pages),
            raw_company_count=len(companies),
            total_companies=total_companies,
        )
        return TheirStackCompanySearchResult(
            status="completed",
            companies=tuple(companies),
            diagnostics=final_diagnostics,
        )


def default_http_post(url: str, headers: dict[str, str], body: bytes, timeout_seconds: float) -> tuple[int, dict[str, Any]]:
    request = Request(url, data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8") or "{}")
            return response.status, payload if isinstance(payload, dict) else {}
    except HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8") or "{}")
        except Exception:
            payload = {}
        return exc.code, payload if isinstance(payload, dict) else {}
    except URLError as exc:
        raise RuntimeError(str(exc.reason)) from exc


def extract_companies(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("companies", "data", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    nested = payload.get("data")
    if isinstance(nested, dict):
        for key in ("companies", "results"):
            value = nested.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def extract_total_companies(payload: dict[str, Any]) -> int | None:
    for key in ("total", "total_results", "totalResults", "total_companies", "totalCompanies"):
        value = payload.get(key)
        if isinstance(value, int):
            return value
    metadata = payload.get("metadata") or payload.get("meta")
    if isinstance(metadata, dict):
        for key in ("total", "total_results", "totalResults", "total_companies", "totalCompanies"):
            value = metadata.get(key)
            if isinstance(value, int):
                return value
    return None

