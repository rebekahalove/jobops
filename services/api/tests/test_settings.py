from pathlib import Path

import pytest

from jobops_api.settings import load_settings


def test_load_settings_uses_app_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("MODEL_PROVIDER", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    (tmp_path / ".env").write_text("APP_ENV=dev\n", encoding="utf-8")
    (tmp_path / ".env.dev").write_text(
        "MODEL_PROVIDER=mock\nDATABASE_URL=postgresql://example\n",
        encoding="utf-8"
    )

    settings = load_settings(tmp_path)

    assert settings.app_env == "dev"
    assert settings.model_provider == "mock"
    assert settings.database_url == "postgresql://example"


def test_load_settings_rejects_path_like_app_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "../prod")

    with pytest.raises(ValueError):
        load_settings(tmp_path)
