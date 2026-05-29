from __future__ import annotations

import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .models import JobUrlVerificationResult, LiveJobSourceResult


def source_result_verification(result: LiveJobSourceResult, *, verify_url: bool) -> JobUrlVerificationResult:
    if result.provenance == "mock":
        return JobUrlVerificationResult(
            status="mock_verified",
            checked_at=datetime.now(timezone.utc),
            summary="Mock job result for local/test mode.",
            final_url=result.job_url,
            posting_date=result.posting_date,
        )
    if not verify_url and result.provenance == "provider_result":
        return JobUrlVerificationResult(
            status=result.url_verification_status or "provider_unverified",
            checked_at=result.url_verification_checked_at or datetime.now(timezone.utc),
            summary=result.url_verification_summary or "Trusted provider result; URL fetch was not required.",
            final_url=result.job_url,
            posting_date=result.posting_date,
        )
    verification = verify_job_url(
        result.job_url,
        expected_title=None if result.provenance == "user_url" else result.title,
        expected_company=None if result.provenance == "user_url" else result.company_name,
    )
    if result.provenance == "provider_result" and verification.status == "failed" and not verification.expired_or_closed:
        return JobUrlVerificationResult(
            status="provider_unverified",
            checked_at=verification.checked_at,
            summary=f"Provider-backed URL could not be fully fetched/verified: {verification.summary}",
            final_url=verification.final_url or result.job_url,
            posting_date=result.posting_date,
        )
    return verification


def verify_job_url(job_url: str, *, expected_title: str | None = None, expected_company: str | None = None) -> JobUrlVerificationResult:
    checked_at = datetime.now(timezone.utc)
    normalized_url = normalize_job_url(job_url)
    if not normalized_url:
        return JobUrlVerificationResult(status="failed", checked_at=checked_at, summary="URL is not valid http(s).")

    request = urllib.request.Request(
        normalized_url,
        headers={
            "User-Agent": "JobOps/0.1 (+https://jobops.local)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            status = getattr(response, "status", 200)
            final_url = response.geturl() if hasattr(response, "geturl") else normalized_url
            content_type = response.headers.get("content-type", "")
            body = response.read(300_000)
    except urllib.error.HTTPError as error:
        return JobUrlVerificationResult(
            status="failed",
            checked_at=checked_at,
            summary=f"Job URL returned HTTP {error.code}.",
            final_url=error.geturl(),
            expired_or_closed=error.code in {404, 410},
        )
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return JobUrlVerificationResult(status="failed", checked_at=checked_at, summary=f"Job URL fetch failed: {type(error).__name__}.")

    if status >= 400:
        return JobUrlVerificationResult(
            status="failed",
            checked_at=checked_at,
            summary=f"Job URL returned HTTP {status}.",
            final_url=final_url,
            expired_or_closed=status in {404, 410},
        )
    if "text/html" not in content_type.lower() and "text/plain" not in content_type.lower() and content_type:
        return JobUrlVerificationResult(
            status="failed",
            checked_at=checked_at,
            summary=f"Job URL returned unsupported content type {content_type[:80]}.",
            final_url=final_url,
        )

    text = decode_response_body(body)
    visible_text = html_to_text(text)
    lower_visible = visible_text.casefold()
    if looks_like_error_or_signin_page(lower_visible):
        return JobUrlVerificationResult(
            status="failed",
            checked_at=checked_at,
            summary="Fetched page appears to be a sign-in, access, or error page.",
            final_url=final_url,
        )
    if looks_like_closed_job_page(lower_visible):
        return JobUrlVerificationResult(
            status="failed",
            checked_at=checked_at,
            summary="Fetched page indicates the job is expired, closed, or no longer available.",
            final_url=final_url,
            expired_or_closed=True,
        )

    title_ok = text_contains_enough(visible_text, expected_title)
    company_ok = text_contains_enough(visible_text, expected_company)
    if expected_title and not title_ok:
        return JobUrlVerificationResult(
            status="failed",
            checked_at=checked_at,
            summary="Fetched page did not confirm the expected job title.",
            final_url=final_url,
        )
    if expected_company and not company_ok:
        return JobUrlVerificationResult(
            status="failed",
            checked_at=checked_at,
            summary="Fetched page did not confirm the expected company.",
            final_url=final_url,
        )

    return JobUrlVerificationResult(
        status="verified",
        checked_at=checked_at,
        summary="Fetched page confirmed the job title and company.",
        final_url=final_url,
        title=expected_title,
        company_name=expected_company,
        description_excerpt=visible_text[:600],
    )


def normalize_job_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    query = [
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
            urlencode(query, doseq=True),
            "",
        )
    )


def decode_response_body(body: bytes) -> str:
    for encoding in ("utf-8", "windows-1252", "latin-1"):
        try:
            return body.decode(encoding)
        except UnicodeDecodeError:
            continue
    return body.decode("utf-8", errors="replace")


def html_to_text(value: str) -> str:
    without_scripts = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    without_tags = re.sub(r"(?s)<[^>]+>", " ", without_scripts)
    return " ".join(without_tags.split())


def looks_like_error_or_signin_page(lower_visible_text: str) -> bool:
    signals = [
        "sign in to continue",
        "login to continue",
        "access denied",
        "forbidden",
        "page not found",
        "not found",
        "something went wrong",
    ]
    return any(signal in lower_visible_text[:4000] for signal in signals)


def looks_like_closed_job_page(lower_visible_text: str) -> bool:
    signals = [
        "job is no longer available",
        "position is no longer available",
        "posting is no longer available",
        "this job has expired",
        "this position has been filled",
        "no longer accepting applications",
        "job posting has closed",
    ]
    return any(signal in lower_visible_text[:6000] for signal in signals)


def text_contains_enough(text: str, expected: str | None) -> bool:
    if not expected:
        return True
    normalized_text = normalize_match_text(text)
    tokens = [token for token in normalize_match_text(expected).split() if len(token) >= 3]
    if not tokens:
        return True
    matches = sum(1 for token in tokens if token in normalized_text)
    return matches >= max(1, min(len(tokens), 2))


def normalize_match_text(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())
