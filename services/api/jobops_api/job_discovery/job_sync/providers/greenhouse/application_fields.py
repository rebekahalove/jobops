from __future__ import annotations

from typing import Any

from ....provider_utils import clean_text_value


def extract_application_fields_from_greenhouse_payload(raw_metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    payload = greenhouse_detail_payload(raw_metadata)
    if not payload:
        return None
    board_token = clean_text_value((raw_metadata or {}).get("ats_board_token"))
    provider_job_id = clean_text_value(payload.get("id") or (raw_metadata or {}).get("id"))
    source_result_id = clean_text_value((raw_metadata or {}).get("source_result_id"))
    questions = normalize_question_list(payload.get("questions"))
    location_questions = normalize_question_list(payload.get("location_questions"))
    compliance_questions = normalize_question_list(payload.get("compliance"))
    demographic_questions = normalize_demographic_questions(payload.get("demographic_questions"))
    data_compliance = normalize_object_list(payload.get("data_compliance"))
    pay_input_ranges = normalize_object_list(payload.get("pay_input_ranges"))
    all_questions = [*questions, *location_questions, *compliance_questions, *demographic_questions.get("questions", [])]
    raw_field_count = sum(len(question.get("fields") or []) for question in all_questions)
    required_labels = [question["label"] for question in all_questions if question.get("required") and question.get("label")]
    optional_labels = [question["label"] for question in all_questions if not question.get("required") and question.get("label")]
    return {
        "provider": "greenhouse",
        "boardToken": board_token,
        "providerJobId": provider_job_id,
        "sourceResultId": source_result_id,
        "questions": questions,
        "locationQuestions": location_questions,
        "complianceQuestions": compliance_questions,
        "demographicQuestions": demographic_questions,
        "dataCompliance": data_compliance,
        "payInputRanges": pay_input_ranges,
        "rawFieldCount": raw_field_count,
        "requiredFieldCount": sum(len(question.get("fields") or []) for question in all_questions if question.get("required")),
        "requiredQuestionLabels": required_labels,
        "optionalQuestionLabels": optional_labels,
        "fileUploadFields": file_upload_fields(all_questions),
        "freeTextQuestionLabels": question_labels_with_field_types(all_questions, {"textarea", "input_text"}),
        "selectQuestionLabels": question_labels_with_field_types(
            all_questions,
            {"multi_value_single_select", "multi_value_multi_select", "single_select", "multi_select"},
        ),
        "urlQuestionLabels": url_question_labels(all_questions),
        "sourceUpdatedAt": clean_text_value(payload.get("updated_at")),
    }


def summarize_greenhouse_application_requirements(application_fields: dict[str, Any] | None) -> dict[str, Any] | None:
    if not application_fields:
        return None
    all_questions = all_normalized_questions(application_fields)
    detected = detected_materials(all_questions)
    short_answers = [
        {
            "label": question["label"],
            "required": bool(question.get("required")),
            "fieldTypes": field_types(question),
            "description": question.get("description"),
        }
        for question in all_questions
        if has_field_type(question, {"textarea"}) and question.get("label")
    ]
    return {
        "provider": "greenhouse",
        "sourceResultId": application_fields.get("sourceResultId"),
        "requiresResume": "resume" in detected,
        "requiresCoverLetter": "cover_letter" in detected,
        "requiresPortfolioUrl": "portfolio_url" in detected,
        "requiresLinkedIn": "linkedin_url" in detected,
        "requiresWebsite": "website_url" in detected,
        "requiresGithub": "github_url" in detected,
        "requiresLocation": "location" in detected,
        "requiresPhone": "phone" in detected,
        "requiresWorkAuthorization": "work_authorization" in detected,
        "requiresSponsorshipAnswer": "sponsorship" in detected,
        "requiresSalaryExpectation": "salary_expectation" in detected,
        "shortAnswerQuestions": short_answers,
        "requiredQuestionLabels": list(application_fields.get("requiredQuestionLabels") or []),
        "optionalQuestionLabels": list(application_fields.get("optionalQuestionLabels") or []),
        "detectedMaterials": sorted(detected),
        "notes": [],
    }


def extract_pay_transparency_from_greenhouse_payload(raw_metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    payload = greenhouse_detail_payload(raw_metadata)
    if not payload:
        return None
    ranges = normalize_object_list(payload.get("pay_input_ranges"))
    if not ranges:
        return None
    normalized_ranges: list[dict[str, Any]] = []
    for item in ranges:
        min_cents = parse_int(item.get("min_cents"))
        max_cents = parse_int(item.get("max_cents"))
        normalized_ranges.append(
            {
                "currency": clean_text_value(item.get("currency_type") or item.get("currency")),
                "min": cents_to_units(min_cents),
                "max": cents_to_units(max_cents),
                "interval": clean_text_value(item.get("interval") or item.get("unit")),
                "title": clean_text_value(item.get("title")),
                "blurb": clean_text_value(item.get("blurb")),
                "raw": item,
            }
        )
    return {"provider": "greenhouse", "rawPayInputRanges": ranges, "normalizedRanges": normalized_ranges}


def greenhouse_detail_payload(raw_metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(raw_metadata, dict):
        return None
    retrieve_payload = raw_metadata.get("job_board_retrieve_payload")
    if isinstance(retrieve_payload, dict):
        return retrieve_payload
    if any(key in raw_metadata for key in ("questions", "location_questions", "pay_input_ranges")):
        return raw_metadata
    return None


def normalize_question_list(value: object) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        raw_items = [value]
    elif isinstance(value, list):
        raw_items = [item for item in value if isinstance(item, dict)]
    else:
        raw_items = []
    questions: list[dict[str, Any]] = []
    for item in raw_items:
        label = clean_text_value(item.get("label") or item.get("name") or item.get("question"))
        if not label and not item.get("fields"):
            continue
        questions.append(
            {
                "label": label,
                "required": bool(item.get("required")),
                "description": clean_text_value(item.get("description") or item.get("help_text")),
                "fields": normalize_fields(item.get("fields")) or normalize_fields(item),
            }
        )
    return questions


def normalize_fields(value: object) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        raw_items = [value]
    elif isinstance(value, list):
        raw_items = [item for item in value if isinstance(item, dict)]
    else:
        raw_items = []
    return [
        {
            "name": clean_text_value(item.get("name")),
            "type": clean_text_value(item.get("type")),
            "values": normalize_values(item.get("values") or item.get("answer_options")),
        }
        for item in raw_items
    ]


def normalize_values(value: object) -> list[Any]:
    if isinstance(value, list):
        return value
    return []


def normalize_demographic_questions(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return {
            "header": clean_text_value(value.get("header")),
            "description": clean_text_value(value.get("description")),
            "questions": normalize_question_list(value.get("questions")),
        }
    if isinstance(value, list):
        return {"header": None, "description": None, "questions": normalize_question_list(value)}
    return {"header": None, "description": None, "questions": []}


def normalize_object_list(value: object) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def all_normalized_questions(application_fields: dict[str, Any]) -> list[dict[str, Any]]:
    demographic = application_fields.get("demographicQuestions") if isinstance(application_fields.get("demographicQuestions"), dict) else {}
    return [
        *list(application_fields.get("questions") or []),
        *list(application_fields.get("locationQuestions") or []),
        *list(application_fields.get("complianceQuestions") or []),
        *list(demographic.get("questions") or []),
    ]


def field_types(question: dict[str, Any]) -> list[str]:
    return [field_type for field in question.get("fields") or [] for field_type in [clean_text_value(field.get("type"))] if field_type]


def has_field_type(question: dict[str, Any], wanted_types: set[str]) -> bool:
    return any(field_type.casefold() in wanted_types for field_type in field_types(question))


def question_labels_with_field_types(questions: list[dict[str, Any]], wanted_types: set[str]) -> list[str]:
    return [question["label"] for question in questions if question.get("label") and has_field_type(question, wanted_types)]


def file_upload_fields(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"label": question.get("label"), "name": field.get("name"), "type": field.get("type")}
        for question in questions
        for field in question.get("fields") or []
        if (clean_text_value(field.get("type")) or "").casefold() == "input_file"
    ]


def url_question_labels(questions: list[dict[str, Any]]) -> list[str]:
    labels: list[str] = []
    for question in questions:
        text = question_text(question)
        if any(token in text for token in ("url", "website", "portfolio", "linkedin", "github", "personal site")):
            labels.append(question.get("label"))
    return [label for label in labels if label]


def detected_materials(questions: list[dict[str, Any]]) -> set[str]:
    detected: set[str] = set()
    for question in questions:
        text = question_text(question)
        if "resume" in text or "cv" in text:
            detected.add("resume")
        if "cover letter" in text:
            detected.add("cover_letter")
        if any(token in text for token in ("portfolio", "work samples", "samples")):
            detected.add("portfolio_url")
        if "linkedin" in text:
            detected.add("linkedin_url")
        if "github" in text:
            detected.add("github_url")
        if any(token in text for token in ("website", "personal site")):
            detected.add("website_url")
        if "phone" in text:
            detected.add("phone")
        if "location" in text:
            detected.add("location")
        if any(token in text for token in ("work authorization", "authorized to work", "right to work")):
            detected.add("work_authorization")
        if any(token in text for token in ("sponsorship", "visa", "require sponsorship")):
            detected.add("sponsorship")
        if any(token in text for token in ("salary", "compensation", "pay expectation")):
            detected.add("salary_expectation")
    return detected


def question_text(question: dict[str, Any]) -> str:
    parts = [question.get("label"), question.get("description")]
    for field in question.get("fields") or []:
        parts.extend([field.get("name"), field.get("type")])
    return " ".join(clean_text_value(part) for part in parts if clean_text_value(part)).casefold()


def parse_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def cents_to_units(value: int | None) -> int | None:
    return int(value / 100) if value is not None else None
