from __future__ import annotations

from pathlib import Path

import pytest

from jobops_api.public_urls import PublicBaseUrlError, resolve_public_app_base_url
from jobops_api.settings import Settings


def test_resolve_public_app_base_url_rejects_missing_value() -> None:
    with pytest.raises(PublicBaseUrlError, match="JOBOPS_APP_BASE_URL is required"):
        resolve_public_app_base_url(make_settings(app_base_url=None))


def test_resolve_public_app_base_url_rejects_localhost_in_prod() -> None:
    with pytest.raises(PublicBaseUrlError, match="cannot point to a local host"):
        resolve_public_app_base_url(make_settings(app_base_url="https://localhost:3002", app_env="prod"))


def test_resolve_public_app_base_url_allows_mounted_https_url_in_prod() -> None:
    assert (
        resolve_public_app_base_url(
            make_settings(app_base_url="https://rebekahalove.dev/jobops/", app_env="prod")
        )
        == "https://rebekahalove.dev/jobops"
    )


def make_settings(*, app_base_url: str | None, app_env: str = "dev") -> Settings:
    return Settings(
        app_env=app_env,
        model_provider="mock",
        default_model="mock",
        cheap_model="mock",
        gemini_api_key=None,
        profile_intake_save_artifacts=False,
        profile_intake_save_raw_text=False,
        company_discovery_search_grounding_enabled=False,
        database_url=None,
        repo_root=Path("."),
        app_base_url=app_base_url,
    )
