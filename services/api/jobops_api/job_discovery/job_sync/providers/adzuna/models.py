from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AdzunaSyncSignatureInput:
    query_text: str
    display_location: str | None
    provider_country: str | None = None
    provider_where: str | None = None
    query_kind: str = "manual"
    source: str = "cli"
    results_per_page: int = 50
    max_pages: int = 1
    freshness_hours: int = 24
    enabled: bool = True
    created_by: str | None = None


@dataclass(frozen=True)
class AdzunaSearchRequest:
    provider_country: str
    api_path: str
    page: int
    what: str
    where: str | None
    what_exclude: str | None
    results_per_page: int


@dataclass(frozen=True)
class AdzunaPageResult:
    request: AdzunaSearchRequest
    results: tuple[object, ...]
    provider_reported_count: int | None = None
    provider_reported_mean: float | None = None


@dataclass(frozen=True)
class AdzunaSearchResponse:
    pages: tuple[AdzunaPageResult, ...]

    @property
    def results(self) -> tuple[object, ...]:
        return tuple(result for page in self.pages for result in page.results)

    @property
    def provider_reported_count(self) -> int | None:
        for page in self.pages:
            if page.provider_reported_count is not None:
                return page.provider_reported_count
        return None

    @property
    def provider_reported_mean(self) -> float | None:
        for page in self.pages:
            if page.provider_reported_mean is not None:
                return page.provider_reported_mean
        return None

    def diagnostics_json(self) -> dict[str, Any]:
        return {
            "providerReportedCount": self.provider_reported_count,
            "providerReportedMean": self.provider_reported_mean,
            "pagesFetched": len(self.pages),
            "pageDiagnostics": [
                {
                    "page": page.request.page,
                    "apiPath": page.request.api_path,
                    "what": page.request.what,
                    "where": page.request.where,
                    "resultsPerPage": page.request.results_per_page,
                    "returnedCount": len(page.results),
                    "providerReportedCount": page.provider_reported_count,
                    "providerReportedMean": page.provider_reported_mean,
                }
                for page in self.pages
            ],
        }
