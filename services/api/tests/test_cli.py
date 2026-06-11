from __future__ import annotations

import sys

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from jobops_api import cli
from jobops_api.db.models import Base
from jobops_api.job_discovery.job_sync.models import JobSyncRequest, JobSyncResult


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


def test_sync_greenhouse_job_boards_cli_passes_options(monkeypatch):
    calls = []

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "jobops-api",
            "sync-greenhouse-job-boards",
            "--board-token",
            "anthropic",
            "--board-token",
            "hightouch",
            "--candidate-slug",
            "rebekah-love",
            "--all-configured",
            "--force",
            "--freshness-hours",
            "12",
            "--max-detail-requests",
            "10",
        ],
    )
    monkeypatch.setattr(cli, "sync_greenhouse_job_boards_command", lambda **kwargs: calls.append(kwargs))

    cli.main()

    assert calls == [
        {
            "board_tokens": ["anthropic", "hightouch"],
            "candidate_slug": "rebekah-love",
            "all_configured": True,
            "force": True,
            "freshness_hours": 12,
            "max_detail_requests": 10,
        }
    ]


def test_upsert_adzuna_sync_signature_cli_passes_options(monkeypatch):
    calls = []

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "jobops-api",
            "upsert-adzuna-sync-signature",
            "--query",
            "AI",
            "--location",
            "Remote UK",
            "--provider-country",
            "gb",
            "--provider-where",
            "Remote",
            "--query-kind",
            "broad_term",
            "--source",
            "cli",
            "--results-per-page",
            "25",
            "--max-pages",
            "2",
            "--freshness-hours",
            "12",
            "--disabled",
            "--created-by",
            "tester",
        ],
    )
    monkeypatch.setattr(cli, "upsert_adzuna_sync_signature_command", lambda **kwargs: calls.append(kwargs))

    cli.main()

    assert calls == [
        {
            "query": "AI",
            "location": "Remote UK",
            "provider_country": "gb",
            "provider_where": "Remote",
            "query_kind": "broad_term",
            "source": "cli",
            "results_per_page": 25,
            "max_pages": 2,
            "freshness_hours": 12,
            "enabled": False,
            "created_by": "tester",
        }
    ]


def test_upsert_adzuna_sync_signature_cli_output_explains_signature_preview(monkeypatch, capsys):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    monkeypatch.setattr(cli, "create_db_engine", lambda: engine)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "jobops-api",
            "upsert-adzuna-sync-signature",
            "--query",
            "AI",
            "--location",
            "Remote UK",
            "--query-kind",
            "broad_term",
            "--max-pages",
            "1",
        ],
    )

    cli.main()

    output = capsys.readouterr().out
    assert "Adzuna sync signature upserted." in output
    assert "sync_key: adzuna:broad:gb:remote-uk:ai" in output
    assert "provider_country: gb" in output
    assert "provider_where: -" in output
    assert "api_path: /v1/api/jobs/gb/search/1" in output
    assert "what: AI" in output
    assert "where: -" in output
    assert "max_pages: 1" in output
    assert "results_per_page: 50" in output
    assert "No provider API call was made" in output
    assert "sync-adzuna-job-signatures --signature-id" in output
    assert "--force --max-pages 1" in output


def test_list_adzuna_sync_signatures_cli_passes_filters(monkeypatch):
    calls = []

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "jobops-api",
            "list-adzuna-sync-signatures",
            "--status",
            "needs_review",
            "--enabled-only",
        ],
    )
    monkeypatch.setattr(cli, "list_adzuna_sync_signatures_command", lambda **kwargs: calls.append(kwargs))

    cli.main()

    assert calls == [{"status": "needs_review", "enabled_only": True}]


def test_sync_adzuna_job_signatures_cli_passes_options(monkeypatch):
    calls = []

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "jobops-api",
            "sync-adzuna-job-signatures",
            "--signature-id",
            "sig-1",
            "--signature-id",
            "sig-2",
            "--force",
            "--freshness-hours",
            "6",
            "--max-pages",
            "1",
        ],
    )
    monkeypatch.setattr(cli, "sync_adzuna_job_signatures_command", lambda **kwargs: calls.append(kwargs))

    cli.main()

    assert calls == [
        {
            "signature_ids": ["sig-1", "sig-2"],
            "all_enabled": False,
            "force": True,
            "freshness_hours": 6,
            "max_pages": 1,
        }
    ]


def test_format_adzuna_sync_result_shows_provider_refresh_details():
    result = JobSyncResult(
        request=JobSyncRequest(
            sync_key="adzuna:broad:gb:remote-uk:ai",
            provider_name="adzuna",
            provider_type="broad_search",
            sync_kind="broad_search",
            provider_country="gb",
            query_text="AI",
            criteria_json={
                "apiPath": "/v1/api/jobs/gb/search/1",
                "what": "AI",
                "where": None,
                "maxPages": 1,
            },
        ),
        status="completed",
        raw_result_count=50,
        normalized_count=49,
        created_count=12,
        updated_count=37,
        diagnostics_json={
            "pagesFetched": 1,
            "providerReportedCount": 123,
        },
    )

    output = cli.format_adzuna_sync_result(result)

    assert output == (
        "adzuna:broad:gb:remote-uk:ai completed api=/v1/api/jobs/gb/search/1 "
        "what=AI where=- pages=1 provider_count=123 raw=50 normalized=49 "
        "created=12 updated=37 failed=0"
    )
