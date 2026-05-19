from pathlib import Path

import pytest

from jobops_api.settings import load_settings


def test_load_settings_uses_app_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("MODEL_PROVIDER", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("JOBOPS_CORS_ORIGINS", raising=False)
    monkeypatch.delenv("JOBOPS_ENABLE_API_DOCS", raising=False)
    monkeypatch.delenv("JOBOPS_INTERNAL_API_KEY", raising=False)

    (tmp_path / ".env").write_text("APP_ENV=dev\n", encoding="utf-8")
    (tmp_path / ".env.dev").write_text(
        "MODEL_PROVIDER=mock\nDATABASE_URL=postgresql://example\nJOBOPS_DEFAULT_CANDIDATE_PROFILE_SLUG=rebekah-love\n",
        encoding="utf-8"
    )

    settings = load_settings(tmp_path)

    assert settings.app_env == "dev"
    assert settings.model_provider == "mock"
    assert settings.database_url == "postgresql://example"
    assert settings.default_candidate_profile_slug == "rebekah-love"
    assert settings.cors_origins == ()
    assert settings.enable_api_docs is True


def test_load_settings_does_not_default_candidate_profile_slug(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("JOBOPS_DEFAULT_CANDIDATE_PROFILE_SLUG", raising=False)

    (tmp_path / ".env").write_text("APP_ENV=dev\n", encoding="utf-8")
    (tmp_path / ".env.dev").write_text("MODEL_PROVIDER=mock\n", encoding="utf-8")

    settings = load_settings(tmp_path)

    assert settings.default_candidate_profile_slug is None


def test_load_settings_rejects_path_like_app_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "../prod")

    with pytest.raises(ValueError):
        load_settings(tmp_path)


def test_load_settings_parses_security_and_cors_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("JOBOPS_CORS_ORIGINS", raising=False)
    monkeypatch.delenv("JOBOPS_ENABLE_API_DOCS", raising=False)
    monkeypatch.delenv("JOBOPS_INTERNAL_API_KEY", raising=False)

    (tmp_path / ".env").write_text("APP_ENV=prod\n", encoding="utf-8")
    (tmp_path / ".env.prod").write_text(
        "\n".join(
            [
                "JOBOPS_INTERNAL_API_KEY=example-secret",
                "JOBOPS_CORS_ORIGINS=https://rebekahalove.dev, https://jobops.rebekahalove.dev, ,",
            ]
        ),
        encoding="utf-8",
    )

    settings = load_settings(tmp_path)

    assert settings.internal_api_key == "example-secret"
    assert settings.cors_origins == ("https://rebekahalove.dev", "https://jobops.rebekahalove.dev")
    assert settings.enable_api_docs is False


def test_load_settings_can_enable_api_docs_in_prod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("JOBOPS_ENABLE_API_DOCS", raising=False)

    (tmp_path / ".env").write_text("APP_ENV=prod\n", encoding="utf-8")
    (tmp_path / ".env.prod").write_text("JOBOPS_ENABLE_API_DOCS=true\n", encoding="utf-8")

    settings = load_settings(tmp_path)

    assert settings.enable_api_docs is True
