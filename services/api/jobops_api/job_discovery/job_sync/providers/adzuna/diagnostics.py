from __future__ import annotations

from typing import Any


SECRET_KEYS = {
    "app_id",
    "appId",
    "app_key",
    "appKey",
    "authorization",
    "cookie",
    "cookies",
    "token",
}


def strip_secret_shaped_keys(raw: dict[str, object]) -> dict[str, object]:
    return {key: strip_secrets(value) for key, value in raw.items() if key.casefold() not in {secret.casefold() for secret in SECRET_KEYS}}


def strip_secrets(value: object) -> object:
    if isinstance(value, dict):
        return strip_secret_shaped_keys(value)
    if isinstance(value, list):
        return [strip_secrets(item) for item in value]
    return value


def page_request_diagnostics(
    *,
    provider_country: str,
    page: int,
    what: str,
    where: str | None,
    what_exclude: str | None,
    results_per_page: int,
) -> dict[str, Any]:
    return {
        "providerName": "adzuna",
        "providerCountry": provider_country,
        "apiPath": f"/v1/api/jobs/{provider_country}/search/{page}",
        "what": what,
        "where": where,
        "whatExclude": what_exclude,
        "resultsPerPage": results_per_page,
        "page": page,
        "contentType": "application/json",
    }
