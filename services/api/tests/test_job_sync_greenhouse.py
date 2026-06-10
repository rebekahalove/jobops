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
from jobops_api.job_discovery.job_sync.greenhouse_service import dedupe_greenhouse_board_sync_targets
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
        result = sync_greenhouse_boards(
            session,
            settings=greenhouse_sync_settings(),
            board_tokens=["vaulttec"],
            include_configured=False,
            force=True,
        )[0]
        source = session.scalar(select(JobListingSource))
        listing = session.scalar(select(JobListing))
        run = session.scalar(select(JobSyncRun))

    assert result.status == "failed"
    assert result.error is not None
    assert "jobs array" in result.error
    assert source is not None
    assert source.is_active is True
    assert source.closed_at is None
    assert listing is not None
    assert listing.is_active is True
    assert run is not None
    assert run.status == "failed"
    assert run.criteria_json["listJobsResponseValid"] is False


def test_greenhouse_failed_list_response_persists_failed_run_after_commit(monkeypatch) -> None:
    engine = create_engine_for_greenhouse_sync_tests()
    monkeypatch_greenhouse_list_payload(monkeypatch, {"unexpected": []})

    with Session(engine) as session:
        result = sync_greenhouse_boards(
            session,
            settings=greenhouse_sync_settings(),
            board_tokens=["vaulttec"],
            include_configured=False,
            force=True,
        )[0]
        session.commit()

    with Session(engine) as session:
        run = session.scalar(select(JobSyncRun))

    assert result.status == "failed"
    assert run is not None
    assert run.status == "failed"
    assert run.error == "Greenhouse list-jobs response did not include a jobs array."
    assert run.criteria_json["listJobsResponseValid"] is False


def test_greenhouse_sync_continues_after_one_board_fails(monkeypatch) -> None:
    engine = create_engine_for_greenhouse_sync_tests()
    requested: list[tuple[str, dict[str, object] | None]] = []

    def fake_fetch_json(url: str, *, params: dict[str, object] | None = None):
        requested.append((url, params))
        if url == "https://boards-api.greenhouse.io/v1/boards/badco/jobs":
            return {"jobs": "oops"}
        if url == "https://boards-api.greenhouse.io/v1/boards/vaulttec/jobs":
            return {"jobs": [greenhouse_list_job_raw(job_id=1, title="Engineer")]}
        if url == "https://boards-api.greenhouse.io/v1/boards/vaulttec/jobs/1":
            return greenhouse_retrieve_job_raw(job_id=1, title="Engineer")
        raise AssertionError(f"Unexpected Greenhouse URL: {url}")

    monkeypatch.setattr("jobops_api.job_discovery.job_sync.providers.greenhouse.client.fetch_json", fake_fetch_json)

    with Session(engine) as session:
        results = sync_greenhouse_boards(
            session,
            settings=greenhouse_sync_settings(),
            board_tokens=["badco", "vaulttec"],
            include_configured=False,
            force=True,
        )
        runs = session.scalars(select(JobSyncRun).order_by(JobSyncRun.sync_key.asc())).all()
        listings = session.scalars(select(JobListing)).all()

    assert [result.status for result in results] == ["failed", "completed"]
    assert [run.status for run in runs] == ["failed", "completed"]
    assert len(listings) == 1
    assert requested[0] == ("https://boards-api.greenhouse.io/v1/boards/badco/jobs", {"content": "true"})
    assert ("https://boards-api.greenhouse.io/v1/boards/vaulttec/jobs", {"content": "true"}) in requested


def test_greenhouse_list_exception_does_not_close_previous_jobs(monkeypatch) -> None:
    engine = create_engine_for_greenhouse_sync_tests()

    def fail_list_jobs(url: str, *, params: dict[str, object] | None = None):
        raise urllib.error.HTTPError(url, 500, "Boom", hdrs=None, fp=None)

    monkeypatch.setattr("jobops_api.job_discovery.job_sync.providers.greenhouse.client.fetch_json", fail_list_jobs)

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

    assert result.status == "failed"
    assert result.error is not None
    assert "HTTP Error 500" in result.error
    assert source is not None
    assert source.is_active is True
    assert source.closed_at is None
    assert listing is not None
    assert listing.is_active is True


def test_greenhouse_dedupe_prefers_company_metadata_over_bare_target() -> None:
    targets = dedupe_greenhouse_board_sync_targets(
        [
            GreenhouseBoardSyncTarget(board_token="vaulttec", source="explicit"),
            GreenhouseBoardSyncTarget(
                board_token="vaulttec/",
                company_id="company-1",
                company_name="Vault-Tec",
                source="candidate_company_board_token",
            ),
        ]
    )

    assert targets == (
        GreenhouseBoardSyncTarget(
            board_token="vaulttec",
            company_id="company-1",
            company_name="Vault-Tec",
            source="candidate_company_board_token",
        ),
    )
    provider_request = GreenhouseJobSyncProvider().build_sync_plan(
        [
            "vaulttec",
            GreenhouseBoardSyncTarget(
                board_token="vaulttec",
                company_id="company-1",
                company_name="Vault-Tec",
                source="candidate_company_board_token",
            ),
        ]
    ).requests[0]

    assert provider_request.company_id == "company-1"
    assert provider_request.company_name == "Vault-Tec"


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


def greenhouse_list_job_raw(*, job_id: int = 44444, title: str = "Product Engineer", board_token: str = "vaulttec") -> dict[str, object]:
    return {
        "id": job_id,
        "internal_job_id": job_id + 11111,
        "title": title,
        "updated_at": "2013-07-02T19:39:23Z",
        "location": {"name": "San Francisco, CA"},
        "absolute_url": f"https://boards.greenhouse.io/{board_token}/jobs/{job_id}",
        "content": "This is the job description.",
    }


def greenhouse_retrieve_job_raw(*, job_id: int = 44444, title: str = "Product Engineer", board_token: str = "vaulttec") -> dict[str, object]:
    return {
        "id": job_id,
        "title": title,
        "updated_at": "2013-07-02T19:39:23Z",
        "location": {"name": "San Francisco, CA"},
        "absolute_url": f"https://boards.greenhouse.io/{board_token}/jobs/{job_id}",
        "content": "This is the retrieved job description.",
    }
