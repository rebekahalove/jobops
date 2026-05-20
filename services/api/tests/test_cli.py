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
        }
    ]
