from __future__ import annotations

import urllib.error
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from jobops_api.db.models import Base, JobListing, JobListingSource, JobSyncRun
from jobops_api.job_discovery.job_sync import sync_greenhouse_boards, upsert_job_listing_from_provider_record
from jobops_api.job_discovery.job_sync.models import JobListingSourceRecord, NormalizedJobListing
from jobops_api.job_discovery.job_sync.providers.greenhouse import (
    GreenhouseBoardSyncTarget,
    GreenhouseJobSyncProvider,
    greenhouse_detail_request,
    merge_greenhouse_job_payloads,
)
from jobops_api.settings import Settings


def test_greenhouse_provider_package_preserves_public_imports() -> None:
    assert GreenhouseJobSyncProvider.provider_name == "greenhouse"
    assert GreenhouseBoardSyncTarget(board_token="vaulttec").board_token == "vaulttec"
    assert greenhouse_detail_request("https://example.test/jobs/1") == {
        "url": "https://example.test/jobs/1",
        "params": {"questions": "true", "pay_transparency": "true"},
    }
    assert callable(merge_greenhouse_job_payloads)


def test_greenhouse_valid_empty_board_closes_previous_jobs(monkeypatch) -> None:
    engine = create_engine_for_greenhouse_sync_tests()
    monkeypatch_greenhouse_list_payload(monkeypatch, {"jobs": []})

    with Session(engine) as session:
        seed_greenhouse_listing(session, provider_job_id="1")
        result = sync_greenhouse_boards(
            session,
            settings=greenhouse_sync_settings(),
            board_tokens=["vaulttec"],
            include_configured=False,
            force=True,
        )[0]
        source = session.scalar(select(JobListingSource))
        listing = session.scalar(select(JobListing))

    assert result.status == "completed"
    assert result.closed_count == 1
    assert source is not None
    assert source.is_active is False
    assert source.close_reason == "missing_from_latest_greenhouse_board_sync"
    assert listing is not None
    assert listing.is_active is False


def test_greenhouse_malformed_list_response_does_not_close_previous_jobs(monkeypatch) -> None:
    engine = create_engine_for_greenhouse_sync_tests()
    monkeypatch_greenhouse_list_payload(monkeypatch, {"jobs": "oops"})

    with Session(engine) as session:
        seed_greenhouse_listing(session, provider_job_id="1")
        try:
            sync_greenhouse_boards(
                session,
                settings=greenhouse_sync_settings(),
                board_tokens=["vaulttec"],
                include_configured=False,
                force=True,
            )
        except ValueError as error:
            assert "jobs array" in str(error)
        else:
            raise AssertionError("Malformed Greenhouse list response should fail sync.")
        source = session.scalar(select(JobListingSource))
        listing = session.scalar(select(JobListing))
        run = session.scalar(select(JobSyncRun))

    assert source is not None
    assert source.is_active is True
    assert source.closed_at is None
    assert listing is not None
    assert listing.is_active is True
    assert run is not None
    assert run.status == "failed"
    assert run.criteria_json["listJobsResponseValid"] is False


def test_greenhouse_list_exception_does_not_close_previous_jobs(monkeypatch) -> None:
    engine = create_engine_for_greenhouse_sync_tests()

    def fail_list_jobs(url: str, *, params: dict[str, object] | None = None):
        raise urllib.error.HTTPError(url, 500, "Boom", hdrs=None, fp=None)

    monkeypatch.setattr("jobops_api.job_discovery.job_sync.providers.greenhouse.client.fetch_json", fail_list_jobs)

    with Session(engine) as session:
        seed_greenhouse_listing(session, provider_job_id="1")
        try:
            sync_greenhouse_boards(
                session,
                settings=greenhouse_sync_settings(),
                board_tokens=["vaulttec"],
                include_configured=False,
                force=True,
            )
        except urllib.error.HTTPError:
            pass
        else:
            raise AssertionError("Greenhouse list exception should fail sync.")
        source = session.scalar(select(JobListingSource))
        listing = session.scalar(select(JobListing))

    assert source is not None
    assert source.is_active is True
    assert source.closed_at is None
    assert listing is not None
    assert listing.is_active is True


def create_engine_for_greenhouse_sync_tests():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def greenhouse_sync_settings() -> Settings:
    return Settings(
        app_env="test",
        model_provider="mock",
        default_model="mock",
        cheap_model="mock",
        gemini_api_key=None,
        profile_intake_save_artifacts=False,
        profile_intake_save_raw_text=False,
        company_discovery_search_grounding_enabled=False,
        database_url=None,
        repo_root=Path(__file__).resolve().parents[2],
    )


def seed_greenhouse_listing(session: Session, *, provider_job_id: str) -> None:
    upsert_job_listing_from_provider_record(
        session,
        listing=NormalizedJobListing(
            title=f"Job {provider_job_id}",
            company_name="Vault-Tec",
            canonical_url=f"https://boards.greenhouse.io/vaulttec/jobs/{provider_job_id}",
            apply_url=f"https://boards.greenhouse.io/vaulttec/jobs/{provider_job_id}",
            source_url=f"https://boards.greenhouse.io/vaulttec/jobs/{provider_job_id}",
            source_updated_at=datetime.now(UTC),
            source_status="active",
        ),
        source=JobListingSourceRecord(
            source_provider="greenhouse",
            provider_type="ats_board",
            provider_job_id=provider_job_id,
            source_result_id=f"vaulttec:{provider_job_id}",
            ats_provider="greenhouse",
            ats_board_token="vaulttec",
            source_url=f"https://boards.greenhouse.io/vaulttec/jobs/{provider_job_id}",
            apply_url=f"https://boards.greenhouse.io/vaulttec/jobs/{provider_job_id}",
            canonical_url=f"https://boards.greenhouse.io/vaulttec/jobs/{provider_job_id}",
            raw_metadata_json={"id": provider_job_id},
            source_status="active",
        ),
    )


def monkeypatch_greenhouse_list_payload(monkeypatch, payload: object) -> None:
    def fake_fetch_json(url: str, *, params: dict[str, object] | None = None):
        assert url == "https://boards-api.greenhouse.io/v1/boards/vaulttec/jobs"
        assert params == {"content": "true"}
        return payload

    monkeypatch.setattr("jobops_api.job_discovery.job_sync.providers.greenhouse.client.fetch_json", fake_fetch_json)
