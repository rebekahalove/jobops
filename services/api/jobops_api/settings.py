from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


APP_ENV_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class Settings:
    app_env: str
    model_provider: str
    default_model: str
    cheap_model: str
    gemini_api_key: str | None
    profile_intake_save_artifacts: bool
    profile_intake_save_raw_text: bool
    company_discovery_search_grounding_enabled: bool
    database_url: str | None
    repo_root: Path
    job_discovery_search_grounding_enabled: bool = True
    job_discovery_source: str = "none"
    job_discovery_providers: tuple[str, ...] = ()
    job_discovery_allow_partial_provider_failures: bool = False
    job_discovery_results_per_provider: int = 20
    adzuna_app_id: str | None = None
    adzuna_app_key: str | None = None
    adzuna_country: str = "us"
    greenhouse_board_tokens: tuple[str, ...] = ()
    greenhouse_company_boards: dict[str, str] | None = None
    llm_request_timeout_seconds: float = 60
    internal_api_key: str | None = None
    cors_origins: tuple[str, ...] = ()
    enable_api_docs: bool = True
    app_base_url: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    resend_api_key: str | None = None
    smtp_from_email: str | None = None


def load_settings(repo_root: Path | None = None) -> Settings:
    root = repo_root or find_repo_root()
    base_values = read_dotenv(root / ".env")

    app_env = os.environ.get("APP_ENV") or base_values.get("APP_ENV") or "dev"
    if not APP_ENV_PATTERN.fullmatch(app_env):
        raise ValueError("APP_ENV must be a simple environment name.")

    environment_values = read_dotenv(root / f".env.{app_env}")
    merged = {
        **base_values,
        **environment_values,
        **os.environ
    }

    model_provider = merged.get("JOBOPS_LLM_PROVIDER") or merged.get("MODEL_PROVIDER", "mock")
    job_discovery_source = merged.get("JOBOPS_JOB_DISCOVERY_SOURCE")
    job_discovery_providers = parse_csv_list(merged.get("JOBOPS_JOB_DISCOVERY_PROVIDERS"))
    if not job_discovery_source:
        job_discovery_source = "mock" if model_provider.strip().lower() == "mock" else "none"
    if not job_discovery_providers:
        job_discovery_providers = (job_discovery_source.strip().lower(),) if job_discovery_source.strip().lower() not in {"", "none"} else ()

    return Settings(
        app_env=app_env,
        model_provider=model_provider,
        default_model=merged.get("JOBOPS_DEFAULT_MODEL", "gemini-2.5-flash"),
        cheap_model=merged.get("JOBOPS_CHEAP_MODEL", "gemini-2.5-flash-lite"),
        gemini_api_key=merged.get("GEMINI_API_KEY"),
        profile_intake_save_artifacts=parse_bool(merged.get("JOBOPS_PROFILE_INTAKE_SAVE_ARTIFACTS")),
        profile_intake_save_raw_text=parse_bool(merged.get("JOBOPS_PROFILE_INTAKE_SAVE_RAW_TEXT")),
        company_discovery_search_grounding_enabled=parse_bool(
            merged.get("JOBOPS_COMPANY_DISCOVERY_SEARCH_GROUNDING"),
            default=True,
        ),
        job_discovery_search_grounding_enabled=parse_bool(
            merged.get("JOBOPS_JOB_DISCOVERY_SEARCH_GROUNDING"),
            default=True,
        ),
        job_discovery_source=job_discovery_source.strip().lower(),
        job_discovery_providers=tuple(provider.strip().lower() for provider in job_discovery_providers if provider.strip()),
        job_discovery_allow_partial_provider_failures=parse_bool(
            merged.get("JOBOPS_JOB_DISCOVERY_ALLOW_PARTIAL_PROVIDER_FAILURES"),
            default=False,
        ),
        job_discovery_results_per_provider=parse_int(
            merged.get("JOBOPS_JOB_DISCOVERY_RESULTS_PER_PROVIDER"),
            default=20,
        ),
        adzuna_app_id=merged.get("JOBOPS_ADZUNA_APP_ID"),
        adzuna_app_key=merged.get("JOBOPS_ADZUNA_APP_KEY"),
        adzuna_country=(merged.get("JOBOPS_ADZUNA_COUNTRY") or "us").strip().lower(),
        greenhouse_board_tokens=parse_csv_list(merged.get("JOBOPS_GREENHOUSE_BOARD_TOKENS")),
        greenhouse_company_boards=parse_json_object(merged.get("JOBOPS_GREENHOUSE_COMPANY_BOARDS")),
        database_url=merged.get("DATABASE_URL"),
        repo_root=root,
        llm_request_timeout_seconds=parse_float(merged.get("JOBOPS_LLM_TIMEOUT_SECONDS"), default=60),
        internal_api_key=merged.get("JOBOPS_INTERNAL_API_KEY"),
        cors_origins=parse_csv_list(merged.get("JOBOPS_CORS_ORIGINS")),
        enable_api_docs=parse_bool(merged.get("JOBOPS_ENABLE_API_DOCS"), default=app_env.lower() != "prod"),
        app_base_url=merged.get("JOBOPS_APP_BASE_URL"),
        smtp_host=merged.get("JOBOPS_SMTP_HOST"),
        smtp_port=parse_int(merged.get("JOBOPS_SMTP_PORT"), default=587),
        smtp_username=merged.get("JOBOPS_SMTP_USERNAME"),
        resend_api_key=merged.get("RESEND_API_KEY"),
        smtp_from_email=merged.get("JOBOPS_SMTP_FROM_EMAIL"),
    )


def parse_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_csv_list(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


def parse_int(value: str | None, *, default: int) -> int:
    if value is None or not value.strip():
        return default
    return int(value)


def parse_float(value: str | None, *, default: float) -> float:
    if value is None or not value.strip():
        return default
    return float(value)


def parse_json_object(value: str | None) -> dict[str, str] | None:
    if value is None or not value.strip():
        return None
    import json

    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        return None
    return {str(key): str(val) for key, val in parsed.items() if val is not None}


def find_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def read_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        key, raw_value = stripped.split("=", 1)
        key = key.strip()
        value = raw_value.strip().strip('"').strip("'")
        if key:
            values[key] = value

    return values
