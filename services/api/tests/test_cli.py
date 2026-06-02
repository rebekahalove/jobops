from __future__ import annotations

import sys

from jobops_api import cli


def test_seed_initial_user_cli_passes_password_and_reset_flag(monkeypatch):
    calls = []

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "jobops-api",
            "seed-initial-user",
            "--email",
            "rebekah@example.com",
            "--username",
            "rebekah-love",
            "--name",
            "Rebekah Love",
            "--password",
            "example initial password",
            "--no-require-reset",
            "--workspace-slug",
            "rebekah-love",
        ],
    )
    monkeypatch.setattr(cli, "seed_initial_user_command", lambda **kwargs: calls.append(kwargs))

    cli.main()

    assert calls == [
        {
            "email": "rebekah@example.com",
            "username": "rebekah-love",
            "name": "Rebekah Love",
            "password": "example initial password",
            "require_reset": False,
            "workspace_slug": "rebekah-love",
            "user_type": "user",
            "update_existing": False,
        }
    ]


def test_seed_initial_user_cli_can_prompt_for_password(monkeypatch):
    calls = []
    prompts = iter(["example prompted password", "example prompted password"])

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "jobops-api",
            "seed-initial-user",
            "--email",
            "rebekah@example.com",
            "--username",
            "rebekah-love",
            "--name",
            "Rebekah Love",
            "--prompt-password",
        ],
    )
    monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt: next(prompts))
    monkeypatch.setattr(cli, "seed_initial_user_command", lambda **kwargs: calls.append(kwargs))

    cli.main()

    assert calls[0]["password"] == "example prompted password"
    assert calls[0]["require_reset"] is True
    assert calls[0]["user_type"] == "user"
    assert calls[0]["update_existing"] is False


def test_seed_initial_user_cli_requires_explicit_admin_flag(monkeypatch):
    calls = []

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "jobops-api",
            "seed-initial-user",
            "--email",
            "admin@example.com",
            "--username",
            "admin-user",
            "--name",
            "Admin User",
            "--password",
            "example initial password",
            "--admin",
            "--update-existing",
        ],
    )
    monkeypatch.setattr(cli, "seed_initial_user_command", lambda **kwargs: calls.append(kwargs))

    cli.main()

    assert calls[0]["user_type"] == "admin"
    assert calls[0]["update_existing"] is True


def test_seed_greenhouse_companies_cli_passes_candidate_slug(monkeypatch):
    calls = []

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "jobops-api",
            "seed-greenhouse-companies",
            "--candidate-slug",
            "rebekah-love",
        ],
    )
    monkeypatch.setattr(cli, "seed_greenhouse_companies_command", lambda **kwargs: calls.append(kwargs))

    cli.main()

    assert calls == [{"candidate_slug": "rebekah-love"}]
