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
    database_url: str | None
    default_candidate_profile_slug: str
    repo_root: Path


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

    return Settings(
        app_env=app_env,
        model_provider=merged.get("JOBOPS_LLM_PROVIDER") or merged.get("MODEL_PROVIDER", "mock"),
        default_model=merged.get("JOBOPS_DEFAULT_MODEL", "gemini-2.5-flash"),
        cheap_model=merged.get("JOBOPS_CHEAP_MODEL", "gemini-2.5-flash-lite"),
        gemini_api_key=merged.get("GEMINI_API_KEY"),
        profile_intake_save_artifacts=parse_bool(merged.get("JOBOPS_PROFILE_INTAKE_SAVE_ARTIFACTS")),
        profile_intake_save_raw_text=parse_bool(merged.get("JOBOPS_PROFILE_INTAKE_SAVE_RAW_TEXT")),
        database_url=merged.get("DATABASE_URL"),
        default_candidate_profile_slug=merged.get("JOBOPS_DEFAULT_CANDIDATE_PROFILE_SLUG", "rebekah-love"),
        repo_root=root
    )


def parse_bool(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "on"}


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
