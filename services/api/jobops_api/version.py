from __future__ import annotations

import os
import subprocess
from pathlib import Path


SAFE_LABEL_PATTERN = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")


def build_version_metadata(*, app: str, app_env: str) -> dict[str, str]:
    metadata = {
        "app": app,
        "releaseChannel": "alpha",
        "environment": normalize_environment(
            safe_label(
                first_value(
                    "APP_ENV",
                    "NETLIFY_CONTEXT",
                    "CONTEXT",
                    "VERCEL_ENV",
                    fallback=app_env,
                ),
                "dev",
            )
        ),
        "commit": short_commit(
            first_value(
                "COMMIT_REF",
                "NETLIFY_COMMIT_REF",
                "GITHUB_SHA",
                "RENDER_GIT_COMMIT",
                "VERCEL_GIT_COMMIT_SHA",
                "CF_PAGES_COMMIT_SHA",
                fallback=git_commit(),
            ),
        ),
    }

    return metadata


def normalize_environment(value: str) -> str:
    normalized = value.strip().lower()
    if normalized == "production":
        return "prod"
    if normalized in {"development", "local"}:
        return "dev"
    if normalized in {"deploy-preview", "branch-deploy"}:
        return "preview"
    return normalized or "dev"


def short_commit(value: str | None) -> str:
    if not value:
        return "local"

    normalized = value.strip()
    if not normalized or not safe_token(normalized):
        return "local"

    return normalized[:7]


def safe_label(value: str | None, fallback: str) -> str:
    if not value:
        return fallback

    normalized = value.strip()
    if not normalized or not safe_token(normalized):
        return fallback

    return normalized


def safe_token(value: str) -> bool:
    return all(character in SAFE_LABEL_PATTERN for character in value)


def first_value(*keys: str, fallback: str | None = None) -> str | None:
    for key in keys:
        value = os.environ.get(key)
        if value and value.strip():
            return value
    return fallback


def git_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[3],
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None
