from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from ...company_canonicalization import normalize_company_name
from .ats import infer_ats_from_urls
from .models import NormalizedCompanyEnrichment


def normalize_theirstack_company(payload: dict[str, Any]) -> NormalizedCompanyEnrichment | None:
    name = clean_text(first_value(payload, "name", "company_name", "companyName"))
    if not name:
        return None

    website_url = clean_url(first_value(payload, "website_url", "websiteUrl", "website", "company_website", "companyWebsite"))
    domain = clean_domain(first_value(payload, "domain", "company_domain", "companyDomain")) or domain_from_url(website_url)
    linkedin_url = clean_url(first_value(payload, "linkedin_url", "linkedinUrl", "linkedin"))
    careers_url = clean_url(first_value(payload, "careers_url", "careersUrl", "jobs_url", "jobsUrl"))

    urls = collect_company_urls(payload, website_url=website_url, linkedin_url=linkedin_url, careers_url=careers_url)
    ats = infer_ats_from_urls(urls)

    source_urls = unique_texts([website_url, linkedin_url, careers_url, *urls, *ats.unsupported_ats_urls])
    metadata = compact_provider_metadata(payload, ats_unsupported_urls=ats.unsupported_ats_urls)
    description = clean_text(first_value(payload, "description", "company_description", "companyDescription"))
    industry = clean_text(first_value(payload, "industry", "industry_name", "industryName"))

    return NormalizedCompanyEnrichment(
        name=name,
        normalized_name=normalize_company_name(name) or None,
        domain=domain,
        website_url=website_url,
        linkedin_url=linkedin_url,
        description=description,
        headquarters_city=clean_text(first_value(payload, "headquarters_city", "headquartersCity", "hq_city", "hqCity")),
        headquarters_country=clean_text(
            first_value(payload, "headquarters_country", "headquartersCountry", "hq_country", "hqCountry", "country")
        ),
        industry=industry,
        employee_count=clean_int(first_value(payload, "employee_count", "employeeCount", "employees")),
        employee_count_range=clean_text(first_value(payload, "employee_count_range", "employeeCountRange", "employees_range")),
        funding_stage=clean_text(first_value(payload, "funding_stage", "fundingStage")),
        total_funding_usd=clean_int(first_value(payload, "total_funding_usd", "totalFundingUsd", "total_funding")),
        technology_names=tuple(extract_slug_or_name_list(payload.get("technologies"), field_name="name")),
        technology_slugs=tuple(extract_slug_or_name_list(payload.get("technologies"), field_name="slug")),
        keyword_slugs=tuple(extract_slug_or_name_list(first_value(payload, "keywords", "keyword_slugs", "keywordSlugs"))),
        num_jobs=clean_int(first_value(payload, "num_jobs", "numJobs")),
        num_jobs_found=clean_int(first_value(payload, "num_jobs_found", "numJobsFound", "jobs_found_count")),
        num_jobs_last_30_days=clean_int(first_value(payload, "num_jobs_last_30_days", "numJobsLast30Days")),
        source_urls=tuple(source_urls),
        source_summary=build_source_summary(name, domain, description, industry),
        greenhouse_board_token=ats.greenhouse_board_token,
        ashby_board_url=ats.ashby_board_url,
        lever_slug=ats.lever_slug,
        unsupported_ats_urls=ats.unsupported_ats_urls,
        raw_provider_metadata=metadata,
    )


def collect_company_urls(
    payload: dict[str, Any],
    *,
    website_url: str | None,
    linkedin_url: str | None,
    careers_url: str | None,
) -> list[str]:
    urls: list[str | None] = [website_url, linkedin_url, careers_url]
    for key in (
        "source_urls",
        "sourceUrls",
        "urls",
        "company_urls",
        "companyUrls",
        "careers_urls",
        "careersUrls",
    ):
        urls.extend(flatten_urls(payload.get(key)))
    urls.extend(extract_job_urls(first_value(payload, "jobs_found", "jobsFound", "jobs")))
    return unique_texts(urls)


def extract_job_urls(value: Any) -> list[str]:
    urls: list[str] = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, str):
            urls.append(item)
        elif isinstance(item, dict):
            for key in ("url", "job_url", "jobUrl", "final_url", "finalUrl", "source_url", "sourceUrl", "apply_url", "applyUrl"):
                url = clean_url(item.get(key))
                if url:
                    urls.append(url)
    return urls


def flatten_urls(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        flattened: list[str] = []
        for item in value:
            if isinstance(item, str):
                flattened.append(item)
            elif isinstance(item, dict):
                flattened.extend(str(v) for v in item.values() if isinstance(v, str))
        return flattened
    return []


def compact_provider_metadata(payload: dict[str, Any], *, ats_unsupported_urls: tuple[str, ...]) -> dict[str, Any]:
    metadata: dict[str, Any] = {"provider": "theirstack"}
    for key in (
        "id",
        "linkedin_url",
        "linkedinUrl",
        "industry",
        "employee_count",
        "employeeCount",
        "employee_count_range",
        "employeeCountRange",
        "funding_stage",
        "fundingStage",
        "total_funding_usd",
        "totalFundingUsd",
        "num_jobs",
        "numJobs",
        "num_jobs_found",
        "numJobsFound",
        "num_jobs_last_30_days",
        "numJobsLast30Days",
    ):
        value = payload.get(key)
        if value not in (None, "", [], {}):
            metadata[key] = value
    technologies = payload.get("technologies")
    if isinstance(technologies, list):
        metadata["technologies"] = technologies[:20]
    keywords = first_value(payload, "keywords", "keyword_slugs", "keywordSlugs")
    if isinstance(keywords, list):
        metadata["keywords"] = keywords[:30]
    if ats_unsupported_urls:
        metadata["unsupportedAtsUrls"] = list(ats_unsupported_urls)
    return metadata


def first_value(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def clean_url(value: Any) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    parsed = urlparse(text if "://" in text else f"https://{text}")
    if not parsed.hostname:
        return None
    return text if "://" in text else f"https://{text}"


def clean_domain(value: Any) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    parsed = urlparse(text if "://" in text else f"https://{text}")
    return (parsed.hostname or text).casefold().removeprefix("www.") or None


def domain_from_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value if "://" in value else f"https://{value}")
    return (parsed.hostname or "").casefold().removeprefix("www.") or None


def clean_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.replace(",", "").strip()
        if stripped.isdigit():
            return int(stripped)
    return None


def extract_slug_or_name_list(value: Any, *, field_name: str | None = None) -> list[str]:
    if not isinstance(value, list):
        return []
    values: list[str | None] = []
    for item in value:
        if isinstance(item, str):
            values.append(item)
        elif isinstance(item, dict):
            if field_name:
                values.append(clean_text(item.get(field_name)))
            else:
                values.append(clean_text(item.get("slug") or item.get("name")))
    return unique_texts(values)


def unique_texts(values: list[str | None] | tuple[str | None, ...]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value:
            continue
        stripped = value.strip()
        key = stripped.casefold()
        if stripped and key not in seen:
            cleaned.append(stripped)
            seen.add(key)
    return cleaned


def build_source_summary(name: str, domain: str | None, description: str | None, industry: str | None) -> str:
    pieces = [f"TheirStack company enrichment for {name}."]
    if domain:
        pieces.append(f"Domain: {domain}.")
    if industry:
        pieces.append(f"Industry: {industry}.")
    if description:
        pieces.append(description[:280])
    return " ".join(pieces)

