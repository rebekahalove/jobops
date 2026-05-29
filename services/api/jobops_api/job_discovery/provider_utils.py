from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from .models import LiveJobSourceResult


def fetch_json(url: str, *, params: dict[str, object] | None = None) -> Any:
    query = urlencode(
        [(key, str(value)) for key, value in (params or {}).items() if value is not None and str(value) != ""],
        doseq=True,
    )
    full_url = f"{url}?{query}" if query else url
    request = urllib.request.Request(
        full_url,
        headers={"User-Agent": "JobOps/0.1 (+https://jobops.local)", "Accept": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def dedupe_provider_results(results: list[LiveJobSourceResult]) -> list[LiveJobSourceResult]:
    deduped: list[LiveJobSourceResult] = []
    seen_urls: set[str] = set()
    seen_provider_ids: set[tuple[str, str]] = set()
    for result in results:
        normalized_url = normalize_job_url_for_dedupe(result.job_url)
        provider_key = (result.source_provider, result.source_result_id or "")
        if normalized_url and normalized_url in seen_urls:
            continue
        if provider_key[1] and provider_key in seen_provider_ids:
            continue
        if normalized_url:
            seen_urls.add(normalized_url)
        if provider_key[1]:
            seen_provider_ids.add(provider_key)
        deduped.append(result)
    return deduped


def normalize_job_url_for_dedupe(value: str | None) -> str | None:
    if not value:
        return None
    from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    filtered_query = [
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=False)
        if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}
    ]
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/") or "/",
            "",
            urlencode(filtered_query, doseq=True),
            "",
        )
    )


def build_adzuna_exclusions(constraints: list[str]) -> str | None:
    return " ".join(term for term in constraints if term in {"defense", "gambling", "crypto", "tobacco", "alcohol", "sports"}) or None


def infer_location_query(latest_user_message: str, target_context: dict[str, Any], private_profile_context: dict[str, Any]) -> str | None:
    text = " ".join(
        [
            latest_user_message,
            json.dumps(target_context, sort_keys=True, default=str)[:2000],
            json.dumps(private_profile_context, sort_keys=True, default=str)[:2000],
        ]
    ).casefold()
    if "remote" in text:
        return None
    if "new york" in text or "nyc" in text:
        return "New York"
    if "louisville" in text:
        return "Louisville"
    return None


def infer_remote_mode(value: str) -> str:
    text = value.casefold()
    if "remote" in text:
        return "remote"
    if "hybrid" in text:
        return "hybrid"
    if "on-site" in text or "onsite" in text:
        return "onsite"
    return "unknown"


def parse_datetime_value(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        try:
            return datetime.fromisoformat(text.split(".")[0])
        except ValueError:
            return None


def format_salary_text(salary_min: object, salary_max: object) -> str | None:
    if salary_min is None and salary_max is None:
        return None
    if salary_min is not None and salary_max is not None:
        return f"{salary_min}-{salary_max}"
    return str(salary_min or salary_max)


def nested_get(value: object, *keys: str) -> object:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def clean_text_value(value: object) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", str(value)).strip()
    return cleaned or None


def safe_log_preview(value: str, *, limit: int) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    return normalized[:limit]


def safe_provider_raw_metadata(raw: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key in ("id", "created", "updated_at", "contract_time", "contract_type", "category", "department", "office"):
        value = raw.get(key)
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = value
    return safe


def html_to_text(value: str) -> str:
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", value, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def compact_unique_strings(values: list[str], *, limit: int) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join(value.split())
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        cleaned.append(normalized)
        if len(cleaned) >= limit:
            break
    return cleaned
