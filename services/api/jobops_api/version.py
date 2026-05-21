from __future__ import annotations

import os
from datetime import UTC, datetime


SAFE_LABEL_PATTERN = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")


def build_version_metadata(*, app: str, app_env: str) -> dict[str, str]:
    metadata = {
        "app": app,
        "releaseChannel": safe_label(first_value("NEXT_PUBLIC_JOBOPS_RELEASE_CHANNEL", "JOBOPS_RELEASE_CHANNEL"), "alpha"),
        "environment": normalize_environment(
            safe_label(
                first_value(
                    "NEXT_PUBLIC_JOBOPS_APP_ENV",
                    "JOBOPS_APP_ENV",
                    "APP_ENV",
                    fallback=app_env,
                ),
                "dev",
            )
        ),
        "commit": short_commit(
            first_value(
                "NEXT_PUBLIC_JOBOPS_COMMIT_SHA",
                "JOBOPS_COMMIT_SHA",
                "COMMIT_REF",
                "NETLIFY_COMMIT_REF",
                "VERCEL_GIT_COMMIT_SHA",
                "RENDER_GIT_COMMIT",
                "GITHUB_SHA",
                "CF_PAGES_COMMIT_SHA",
            )
        ),
    }

    build_time = safe_build_time(first_value("NEXT_PUBLIC_JOBOPS_BUILD_TIME", "JOBOPS_BUILD_TIME", "BUILD_TIME"))
    if build_time:
        metadata["buildTime"] = build_time

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


def safe_build_time(value: str | None) -> str | None:
    if not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC).isoformat().replace("+00:00", "Z")
    except ValueError:
        return None


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
