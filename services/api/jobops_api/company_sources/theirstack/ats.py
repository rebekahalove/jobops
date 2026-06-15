from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

from ...job_discovery.greenhouse_utils import canonical_greenhouse_jobs_api_url, parse_greenhouse_url


@dataclass(frozen=True)
class AtsInference:
    greenhouse_board_token: str | None = None
    greenhouse_jobs_api_url: str | None = None
    ashby_board_url: str | None = None
    lever_slug: str | None = None
    unsupported_ats_urls: tuple[str, ...] = ()


@dataclass
class _AtsAccumulator:
    greenhouse_board_token: str | None = None
    greenhouse_jobs_api_url: str | None = None
    ashby_board_url: str | None = None
    lever_slug: str | None = None
    unsupported_ats_urls: list[str] = field(default_factory=list)


def infer_ats_from_urls(urls: list[str | None] | tuple[str | None, ...]) -> AtsInference:
    accumulator = _AtsAccumulator()
    seen_unsupported: set[str] = set()
    for value in urls:
        parsed = infer_ats_from_url(value)
        if parsed.greenhouse_board_token and not accumulator.greenhouse_board_token:
            accumulator.greenhouse_board_token = parsed.greenhouse_board_token
            accumulator.greenhouse_jobs_api_url = parsed.greenhouse_jobs_api_url
        if parsed.ashby_board_url and not accumulator.ashby_board_url:
            accumulator.ashby_board_url = parsed.ashby_board_url
        if parsed.lever_slug and not accumulator.lever_slug:
            accumulator.lever_slug = parsed.lever_slug
        for unsupported in parsed.unsupported_ats_urls:
            key = unsupported.casefold()
            if key not in seen_unsupported:
                accumulator.unsupported_ats_urls.append(unsupported)
                seen_unsupported.add(key)

    return AtsInference(
        greenhouse_board_token=accumulator.greenhouse_board_token,
        greenhouse_jobs_api_url=accumulator.greenhouse_jobs_api_url,
        ashby_board_url=accumulator.ashby_board_url,
        lever_slug=accumulator.lever_slug,
        unsupported_ats_urls=tuple(accumulator.unsupported_ats_urls),
    )


def infer_ats_from_url(value: str | None) -> AtsInference:
    if not value:
        return AtsInference()
    url = value.strip()
    if not url:
        return AtsInference()
    greenhouse = parse_greenhouse_url(url)
    if greenhouse is not None:
        return AtsInference(
            greenhouse_board_token=greenhouse.board_token,
            greenhouse_jobs_api_url=canonical_greenhouse_jobs_api_url(greenhouse.board_token),
        )

    parsed = urlparse(url if "://" in url else f"https://{url}")
    hostname = (parsed.hostname or "").casefold().removeprefix("www.")
    path_parts = [part for part in parsed.path.split("/") if part]

    if hostname == "jobs.ashbyhq.com" and path_parts:
        org = path_parts[0].strip()
        if org:
            return AtsInference(ashby_board_url=f"https://jobs.ashbyhq.com/{org}")

    if hostname == "jobs.lever.co" and path_parts:
        slug = path_parts[0].strip()
        if slug:
            return AtsInference(lever_slug=slug)

    if _is_unsupported_ats_host(hostname):
        return AtsInference(unsupported_ats_urls=(url,))

    return AtsInference()


def _is_unsupported_ats_host(hostname: str) -> bool:
    if not hostname:
        return False
    return (
        "workdayjobs.com" in hostname
        or hostname == "apply.workable.com"
        or hostname.endswith(".workable.com")
        or "myworkdayjobs.com" in hostname
    )

