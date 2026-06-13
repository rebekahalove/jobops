from __future__ import annotations


REJECTION_REASON_CODES = {
    "location",
    "work_mode",
    "compensation",
    "role_title",
    "seniority",
    "skills_or_tech_stack",
    "employment_type",
    "company",
    "industry_or_domain",
    "source_freshness",
    "closed_or_inactive",
    "user_instruction",
    "other",
}

RESETTABLE_FIELDS_BY_REASON = {
    "location": "job_location_target_id,location_country,location_region,location_city,location_metro,location_display",
    "work_mode": "remote_work_mode",
    "compensation": "salary_min,salary_max,salary_currency,salary_text",
    "role_title": "title",
    "seniority": "title,full_description",
    "skills_or_tech_stack": "full_description,description_excerpt",
    "employment_type": "employment_type",
    "company": "company_id,company_name",
    "industry_or_domain": "company,profile,domain",
    "source_freshness": "posting_date,source_updated_at,last_seen_at",
    "closed_or_inactive": "is_active,source_status,closed_at",
    "user_instruction": "latest_chat_instruction",
    "other": "general",
}


def normalize_reason_codes(values: list[str] | tuple[str, ...] | None) -> list[str]:
    normalized: list[str] = []
    for value in values or ["other"]:
        code = str(value or "").strip().casefold()
        if code not in REJECTION_REASON_CODES:
            code = "other"
        if code not in normalized:
            normalized.append(code)
    return normalized or ["other"]


def resettable_field_for_reason(reason_code: str) -> str:
    return RESETTABLE_FIELDS_BY_REASON.get(reason_code, RESETTABLE_FIELDS_BY_REASON["other"])
