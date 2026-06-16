from __future__ import annotations

from html import escape, unescape
from html.parser import HTMLParser
import json
import re
import urllib.request
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any
from urllib.parse import urlencode

ADZUNA_COUNTRY_CURRENCY_CODES = {
    "at": "EUR",
    "au": "AUD",
    "be": "EUR",
    "br": "BRL",
    "ca": "CAD",
    "ch": "CHF",
    "de": "EUR",
    "es": "EUR",
    "fr": "EUR",
    "gb": "GBP",
    "ie": "EUR",
    "in": "INR",
    "it": "EUR",
    "mx": "MXN",
    "nl": "EUR",
    "nz": "NZD",
    "pl": "PLN",
    "sg": "SGD",
    "us": "USD",
    "za": "ZAR",
}


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


EXCLUSION_TERM_STOP_WORDS = {
    "a",
    "about",
    "all",
    "also",
    "an",
    "and",
    "any",
    "apply",
    "avoid",
    "career",
    "careers",
    "companies",
    "company",
    "contractor",
    "contractors",
    "do",
    "dont",
    "employer",
    "employers",
    "exclude",
    "excluding",
    "for",
    "from",
    "group",
    "groups",
    "industry",
    "industries",
    "job",
    "jobs",
    "not",
    "of",
    "opportunities",
    "opportunity",
    "or",
    "organization",
    "organizations",
    "orgs",
    "posting",
    "postings",
    "related",
    "relating",
    "role",
    "roles",
    "sector",
    "sectors",
    "supporter",
    "supporters",
    "the",
    "to",
    "want",
    "with",
    "without",
    "work",
    "working",
}


def build_adzuna_exclusions(constraints: list[str]) -> str | None:
    terms: list[str] = []
    for constraint in constraints:
        terms.extend(normalize_exclusion_terms(constraint))
    return " ".join(compact_unique_strings(terms, limit=20)) or None


def normalize_exclusion_terms(value: object) -> list[str]:
    cleaned = clean_text_value(value)
    if not cleaned:
        return []
    normalized = cleaned.casefold().replace("don't", "dont").replace("do not", "dont")
    parts = re.split(r"[,;]+|\s+\b(?:and|or|but|plus)\b\s+", normalized)
    terms: list[str] = []
    for part in parts:
        tokens = [
            token
            for token in re.findall(r"[a-z0-9][a-z0-9+-]*", part)
            if len(token) >= 2 and token not in EXCLUSION_TERM_STOP_WORDS
        ]
        if not tokens:
            continue
        terms.append(" ".join(tokens[:5]))
    return compact_unique_strings(terms, limit=20)


def normalize_text_for_constraint_matching(value: object) -> str:
    cleaned = clean_text_value(value) or ""
    return re.sub(r"[^a-z0-9+]+", " ", cleaned.casefold()).strip()


REMOTE_LOCATION_RE = re.compile(r"\b(remote|work\s+from\s+home|wfh|distributed)\b", flags=re.IGNORECASE)
COMMAND_LOCATION_RE = re.compile(
    r"\b(?:in|near|around|within|based\s+in|located\s+in|from)\s+(?P<location>[^.?!\n]+)",
    flags=re.IGNORECASE,
)
LOCATION_TRAILING_STOP_RE = re.compile(
    r"\b(?:as\s+well|but|for|that|to\s+apply|who|with|while|please|if|unless)\b",
    flags=re.IGNORECASE,
)
LOCATION_GENERIC_TERMS = {
    "apply",
    "career",
    "careers",
    "company",
    "companies",
    "job",
    "jobs",
    "office",
    "offices",
    "opening",
    "openings",
    "opportunity",
    "opportunities",
    "position",
    "positions",
    "role",
    "roles",
}
LOCATION_FIELD_KEYS = {
    "currentLocation",
    "current_location",
    "location",
    "locations",
    "preferredLocation",
    "preferred_location",
    "preferredLocations",
    "preferred_locations",
    "targetLocation",
    "target_location",
    "targetLocations",
    "target_locations",
}
PREFERRED_LOCATION_FIELD_KEYS = {
    "preferredLocation",
    "preferred_location",
    "preferredLocations",
    "preferred_locations",
    "targetLocation",
    "target_location",
    "targetLocations",
    "target_locations",
}


def infer_location_query(latest_user_message: str, target_context: dict[str, Any], private_profile_context: dict[str, Any]) -> str | None:
    if text_indicates_remote(latest_user_message):
        return None
    command_location = extract_location_from_command(latest_user_message)
    if command_location:
        return command_location
    if context_indicates_remote(target_context) or context_indicates_remote(private_profile_context):
        return None
    return first_structured_location(target_context, private_profile_context)


def text_indicates_remote(value: object) -> bool:
    return bool(isinstance(value, str) and REMOTE_LOCATION_RE.search(value))


def extract_location_from_command(value: object) -> str | None:
    text = clean_text_value(value)
    if not text:
        return None
    for match in COMMAND_LOCATION_RE.finditer(text):
        candidate = LOCATION_TRAILING_STOP_RE.split(match.group("location"), maxsplit=1)[0]
        location = clean_location_value(candidate)
        if location:
            return location
    return None


def context_indicates_remote(value: object) -> bool:
    for location in iter_structured_location_values(value):
        if text_indicates_remote(location):
            return True
    return False


def first_structured_location(*contexts: object) -> str | None:
    fallback_locations: list[str] = []
    for context in contexts:
        preferred = [
            location
            for location in iter_structured_location_values(context, preferred_only=True)
            if not text_indicates_remote(location)
        ]
        if preferred:
            return preferred[0]
        fallback_locations.extend(
            location
            for location in iter_structured_location_values(context)
            if not text_indicates_remote(location)
        )
    return fallback_locations[0] if fallback_locations else None


def iter_structured_location_values(value: object, *, preferred_only: bool = False) -> list[str]:
    if isinstance(value, str):
        return split_location_values(value)
    if isinstance(value, (list, tuple, set)):
        locations: list[str] = []
        for item in value:
            locations.extend(iter_structured_location_values(item, preferred_only=preferred_only))
        return locations
    if not isinstance(value, dict):
        return []

    allowed_keys = PREFERRED_LOCATION_FIELD_KEYS if preferred_only else LOCATION_FIELD_KEYS
    locations = []
    for key, item in value.items():
        if str(key) in allowed_keys:
            locations.extend(iter_structured_location_values(item, preferred_only=False))
            continue
        if isinstance(item, dict):
            locations.extend(iter_structured_location_values(item, preferred_only=preferred_only))
    return compact_unique_strings(locations, limit=20)


def split_location_values(value: str) -> list[str]:
    locations: list[str] = []
    for part in re.split(r";|\n|\s+\|\s+", value):
        location = clean_location_value(part)
        if location:
            locations.append(location)
    return compact_unique_strings(locations, limit=10)


def clean_location_value(value: object) -> str | None:
    cleaned = clean_text_value(value)
    if not cleaned:
        return None
    cleaned = re.sub(r"^[,;:\-\s]+|[,;:\-\s]+$", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    normalized = cleaned.casefold()
    if not normalized or normalized in LOCATION_GENERIC_TERMS or text_indicates_remote(cleaned):
        return None
    if not re.search(r"[a-zA-Z]", cleaned):
        return None
    if len(cleaned) > 80:
        return None
    return cleaned


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


def infer_adzuna_currency_code(country: str | None) -> str | None:
    if not country:
        return None
    return ADZUNA_COUNTRY_CURRENCY_CODES.get(country.strip().lower())


def parse_whole_currency_amount(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if amount < 0:
        return None
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def format_salary_text(salary_min: object, salary_max: object, *, currency_code: str | None = None) -> str | None:
    parsed_min = parse_whole_currency_amount(salary_min)
    parsed_max = parse_whole_currency_amount(salary_max)
    if parsed_min is None and parsed_max is None:
        return None
    prefix = f"{currency_code.upper()} " if currency_code else ""
    if parsed_min is not None and parsed_max is not None:
        if parsed_min == parsed_max:
            return f"{prefix}{parsed_min:,}"
        return f"{prefix}{parsed_min:,}-{parsed_max:,}"
    return f"{prefix}{(parsed_min if parsed_min is not None else parsed_max):,}"


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


def sanitize_job_description_html(value: str | None) -> str | None:
    cleaned = decode_html_markup(value)
    if not cleaned or "<" not in cleaned:
        return None
    sanitizer = JobDescriptionHtmlSanitizer()
    sanitizer.feed(cleaned)
    sanitizer.close()
    html = re.sub(r"\s+", " ", "".join(sanitizer.parts)).strip()
    return html or None


def decode_html_markup(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip()
    for _ in range(3):
        decoded = unescape(cleaned)
        if decoded == cleaned:
            break
        cleaned = decoded
    return cleaned.strip() or None


class JobDescriptionHtmlSanitizer(HTMLParser):
    ALLOWED_TAGS = {"h2", "h3", "p", "ul", "ol", "li", "strong", "em", "a", "br"}
    TAG_ALIASES = {"h1": "h2", "h4": "h3", "h5": "h3", "h6": "h3", "b": "strong", "i": "em"}
    SKIPPED_TAGS = {"script", "style", "iframe", "object", "embed", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = self.normalize_tag(tag)
        if normalized_tag in self.SKIPPED_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth or normalized_tag not in self.ALLOWED_TAGS:
            return
        if normalized_tag == "br":
            self.parts.append("<br>")
            return
        if normalized_tag == "a":
            href = safe_html_href(dict(attrs).get("href"))
            if href:
                self.parts.append(f'<a href="{escape(href, quote=True)}" rel="noopener noreferrer" target="_blank">')
            else:
                self.parts.append("<a>")
            return
        self.parts.append(f"<{normalized_tag}>")

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = self.normalize_tag(tag)
        if normalized_tag in self.SKIPPED_TAGS:
            if self.skip_depth:
                self.skip_depth -= 1
            return
        if self.skip_depth or normalized_tag not in self.ALLOWED_TAGS or normalized_tag == "br":
            return
        if normalized_tag == "a":
            self.parts.append("</a>")
            return
        self.parts.append(f"</{normalized_tag}>")

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        self.parts.append(escape(data, quote=False))

    def handle_entityref(self, name: str) -> None:
        if self.skip_depth:
            return
        self.parts.append(escape(unescape(f"&{name};"), quote=False))

    def handle_charref(self, name: str) -> None:
        if self.skip_depth:
            return
        self.parts.append(escape(unescape(f"&#{name};"), quote=False))

    def normalize_tag(self, tag: str) -> str:
        lowered = tag.lower()
        return self.TAG_ALIASES.get(lowered, lowered)


def safe_html_href(value: str | None) -> str | None:
    if not value:
        return None
    href = value.strip()
    if href.startswith(("http://", "https://")):
        return href
    return None


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
