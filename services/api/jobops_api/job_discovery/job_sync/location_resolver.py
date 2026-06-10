from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.models import JobLocationTarget, JobProviderLocationMapping
from .location_country import normalize_provider_country_code
from .models import JobSyncLocation


@dataclass(frozen=True)
class SeedLocationMapping:
    display_name: str
    normalized_key: str
    location_kind: str
    city: str | None
    region: str | None
    country_code: str
    country_name: str
    provider_name: str
    provider_country: str
    provider_where: str | None
    confidence: str = "high"
    verification_status: str = "verified"


INITIAL_LOCATION_MAPPINGS: tuple[SeedLocationMapping, ...] = (
    SeedLocationMapping(
        display_name="Remote US",
        normalized_key="remote-us",
        location_kind="remote_country",
        city=None,
        region=None,
        country_code="US",
        country_name="United States",
        provider_name="adzuna",
        provider_country="us",
        provider_where=None,
    ),
    SeedLocationMapping(
        display_name="Remote UK",
        normalized_key="remote-uk",
        location_kind="remote_country",
        city=None,
        region=None,
        country_code="GB",
        country_name="United Kingdom",
        provider_name="adzuna",
        provider_country="gb",
        provider_where=None,
    ),
    SeedLocationMapping(
        display_name="Louisville, KY",
        normalized_key="louisville-ky",
        location_kind="city",
        city="Louisville",
        region="KY",
        country_code="US",
        country_name="United States",
        provider_name="adzuna",
        provider_country="us",
        provider_where="Louisville, Kentucky",
    ),
    SeedLocationMapping(
        display_name="London, UK",
        normalized_key="london-uk",
        location_kind="city",
        city="London",
        region=None,
        country_code="GB",
        country_name="United Kingdom",
        provider_name="adzuna",
        provider_country="gb",
        provider_where="London",
    ),
    SeedLocationMapping(
        display_name="Manchester, UK",
        normalized_key="manchester-uk",
        location_kind="city",
        city="Manchester",
        region=None,
        country_code="GB",
        country_name="United Kingdom",
        provider_name="adzuna",
        provider_country="gb",
        provider_where="Manchester",
    ),
)


def normalize_location_key(value: str | None) -> str:
    cleaned = " ".join((value or "").replace(",", " ").split()).strip().casefold()
    normalized = re.sub(r"[^a-z0-9]+", "-", cleaned).strip("-")
    return normalized or "any-location"


def infer_provider_country(value: str | None, *, default_provider_country: str | None = None) -> str | None:
    cleaned = f" {normalize_location_key(value).replace('-', ' ')} "
    if any(token in cleaned for token in (" uk ", " gb ", " gbr ", " united kingdom ", " great britain ")):
        return "gb"
    if any(token in cleaned for token in (" us ", " usa ", " united states ", " america ")):
        return "us"
    if re.search(r"\b[a-z]+ ky\b", cleaned):
        return "us"
    return normalize_provider_country_code(default_provider_country)


def ensure_initial_job_location_mappings(session: Session) -> None:
    for seed in INITIAL_LOCATION_MAPPINGS:
        target = session.scalar(select(JobLocationTarget).where(JobLocationTarget.normalized_key == seed.normalized_key))
        if target is None:
            target = JobLocationTarget(
                display_name=seed.display_name,
                normalized_key=seed.normalized_key,
                location_kind=seed.location_kind,
                city=seed.city,
                region=seed.region,
                country_code=seed.country_code,
                country_name=seed.country_name,
                raw_inputs_json=[seed.display_name],
                confidence=seed.confidence,
                verification_status=seed.verification_status,
                source="seed",
            )
            session.add(target)
            session.flush()
        mapping = session.scalar(
            select(JobProviderLocationMapping).where(
                JobProviderLocationMapping.job_location_target_id == target.id,
                JobProviderLocationMapping.provider_name == seed.provider_name,
            )
        )
        if mapping is None:
            session.add(
                JobProviderLocationMapping(
                    job_location_target_id=target.id,
                    provider_name=seed.provider_name,
                    provider_country=seed.provider_country,
                    provider_where=seed.provider_where,
                    display_location=seed.display_name,
                    confidence=seed.confidence,
                    verification_status=seed.verification_status,
                    source="seed",
                    diagnostics_json={"seeded": True},
                )
            )
    session.flush()


def resolve_or_create_job_location_target(
    session: Session,
    display_location: str | None,
    *,
    source: str = "auto",
    provider_country: str | None = None,
) -> JobLocationTarget:
    ensure_initial_job_location_mappings(session)
    display = clean_display_location(display_location)
    normalized_key = normalize_location_key(display)
    target = session.scalar(select(JobLocationTarget).where(JobLocationTarget.normalized_key == normalized_key))
    now = datetime.now(UTC)
    if target is not None:
        raw_inputs = list(target.raw_inputs_json or [])
        if display and display not in raw_inputs:
            raw_inputs.append(display)
            target.raw_inputs_json = raw_inputs
        target.last_seen_at = now
        session.flush()
        return target
    inferred_country = country_code_for_provider_country(
        infer_provider_country(display, default_provider_country=provider_country)
    )
    target = JobLocationTarget(
        display_name=display,
        normalized_key=normalized_key,
        location_kind=infer_location_kind(display),
        city=infer_city(display),
        region=infer_region(display),
        country_code=inferred_country,
        country_name=country_name_for_code(inferred_country),
        raw_inputs_json=[display] if display else [],
        confidence="low",
        verification_status="needs_review",
        source=source,
        last_seen_at=now,
    )
    session.add(target)
    session.flush()
    return target


def resolve_provider_location_mapping(
    session: Session,
    *,
    provider_name: str,
    display_location: str | None,
    default_provider_country: str | None = None,
) -> JobProviderLocationMapping:
    target = resolve_or_create_job_location_target(session, display_location)
    mapping = session.scalar(
        select(JobProviderLocationMapping).where(
            JobProviderLocationMapping.job_location_target_id == target.id,
            JobProviderLocationMapping.provider_name == provider_name,
        )
    )
    if mapping is not None:
        return mapping
    display = clean_display_location(display_location)
    inferred_provider_country = infer_provider_country(display, default_provider_country=default_provider_country)
    provider_where = infer_provider_where(display, target=target)
    diagnostics: dict[str, Any] = {
        "autoCreated": True,
        "normalizedLocationKey": target.normalized_key,
        "needsReviewReason": "No verified provider location mapping existed.",
    }
    if target.country_code is None and normalize_provider_country_code(default_provider_country):
        diagnostics["providerCountrySource"] = "default_provider_country"
    mapping = JobProviderLocationMapping(
        job_location_target_id=target.id,
        provider_name=provider_name,
        provider_country=inferred_provider_country,
        provider_where=provider_where,
        display_location=display,
        confidence="low",
        verification_status="needs_review",
        source="inferred",
        diagnostics_json=diagnostics,
    )
    session.add(mapping)
    session.flush()
    return mapping


def resolve_or_create_job_location_from_provider_payload(
    session: Session,
    *,
    provider_name: str,
    raw_display_location: str | None,
    provider_location_payload: dict[str, Any] | None = None,
    provider_country: str | None = None,
    source: str = "provider_job_location",
) -> JobLocationTarget:
    if provider_name == "adzuna" and provider_location_payload:
        area = provider_location_payload.get("area")
        if isinstance(area, list) and area:
            country_code = normalize_country_code(area[0])
            region = clean_optional_text(area[1]) if len(area) > 1 else None
            city = clean_optional_text(area[-1]) if len(area) > 1 else None
            display = f"{city}, {region}" if city and region else clean_display_location(raw_display_location)
            normalized_key = normalize_location_key(" ".join(part for part in (city, region, country_code) if part))
            return resolve_or_create_structured_job_location_target(
                session,
                display_name=display,
                normalized_key=normalized_key,
                location_kind="city" if city else "raw",
                city=city,
                region=region,
                country_code=country_code,
                country_name=country_name_for_code(country_code),
                raw_input=raw_display_location,
                confidence="medium",
                verification_status="provider_inferred",
                source=source,
            )
    return resolve_or_create_job_location_target(
        session,
        raw_display_location,
        source=source,
        provider_country=provider_country,
    )


def resolve_or_create_structured_job_location_target(
    session: Session,
    *,
    display_name: str,
    normalized_key: str,
    location_kind: str,
    city: str | None,
    region: str | None,
    country_code: str | None,
    country_name: str | None,
    raw_input: str | None,
    confidence: str,
    verification_status: str,
    source: str,
) -> JobLocationTarget:
    ensure_initial_job_location_mappings(session)
    target = session.scalar(select(JobLocationTarget).where(JobLocationTarget.normalized_key == normalized_key))
    now = datetime.now(UTC)
    if target is None:
        target = JobLocationTarget(
            display_name=display_name,
            normalized_key=normalized_key,
            location_kind=location_kind,
            city=city,
            region=region,
            country_code=country_code,
            country_name=country_name,
            raw_inputs_json=[raw_input] if raw_input else [display_name],
            confidence=confidence,
            verification_status=verification_status,
            source=source,
            last_seen_at=now,
        )
        session.add(target)
        session.flush()
        return target
    raw_inputs = list(target.raw_inputs_json or [])
    for value in (raw_input, display_name):
        if value and value not in raw_inputs:
            raw_inputs.append(value)
    target.raw_inputs_json = raw_inputs
    target.last_seen_at = now
    session.flush()
    return target


def job_sync_location_from_mapping(
    target: JobLocationTarget,
    mapping: JobProviderLocationMapping,
) -> JobSyncLocation:
    return JobSyncLocation(
        display_location=target.display_name,
        provider_country=mapping.provider_country or "",
        provider_where=mapping.provider_where,
        target_country=target.country_name,
        target_location_kind=target.location_kind,
        location_city=target.city,
        location_region=target.region,
        location_country=target.country_code,
        location_metro=target.city,
        location_confidence=mapping.confidence,
        normalized_key=target.normalized_key,
        target_id=target.id,
        provider_mapping_id=mapping.id,
        provider_mapping_confidence=mapping.confidence,
        provider_mapping_status=mapping.verification_status,
    )


def clean_display_location(value: str | None) -> str:
    cleaned = " ".join((value or "Any location").replace(",", ", ").split()).strip(" ,")
    return cleaned or "Any location"


def clean_optional_text(value: object) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(str(value).split()).strip()
    return cleaned or None


def infer_location_kind(value: str | None) -> str:
    cleaned = normalize_location_key(value)
    if cleaned.startswith("remote-") or cleaned in {"remote-us", "remote-uk"}:
        return "remote_country"
    if cleaned == "any-location":
        return "any"
    return "city" if "-" in cleaned else "raw"


def infer_city(value: str | None) -> str | None:
    display = clean_display_location(value)
    if display.casefold().startswith("remote") or display == "Any location":
        return None
    return display.split(",")[0].strip() or None


def infer_region(value: str | None) -> str | None:
    display = clean_display_location(value)
    parts = [part.strip() for part in display.split(",")]
    if len(parts) >= 2 and len(parts[1]) <= 3:
        return parts[1].upper()
    return None


def infer_provider_where(value: str | None, *, target: JobLocationTarget) -> str | None:
    if target.location_kind == "remote_country":
        return None
    display = clean_display_location(value)
    lowered = normalize_location_key(display)
    for suffix in ("-uk", "-gb", "-gbr", "-united-kingdom"):
        if lowered.endswith(suffix):
            return display[: -len(suffix.replace("-", " "))].strip(" ,") or target.city or display
    if lowered.endswith("-us") or lowered.endswith("-usa") or lowered.endswith("-united-states"):
        return target.city or display
    return display


def country_code_for_provider_country(provider_country: str | None) -> str | None:
    if provider_country == "gb":
        return "GB"
    if provider_country == "us":
        return "US"
    return provider_country.upper() if provider_country else None


def normalize_country_code(value: object) -> str | None:
    cleaned = clean_optional_text(value)
    if not cleaned:
        return None
    provider_country = normalize_provider_country_code(cleaned)
    if provider_country:
        return country_code_for_provider_country(provider_country)
    return cleaned.upper()


def country_name_for_code(country_code: str | None) -> str | None:
    if country_code == "GB":
        return "United Kingdom"
    if country_code == "US":
        return "United States"
    return None
