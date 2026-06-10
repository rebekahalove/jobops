from __future__ import annotations


def normalize_provider_country_code(value: str | None) -> str | None:
    cleaned = (value or "").strip().casefold()
    if cleaned in {"uk", "gb", "gbr", "united kingdom", "great britain"}:
        return "gb"
    if cleaned in {"us", "usa", "united states", "united states of america"}:
        return "us"
    return cleaned or None
