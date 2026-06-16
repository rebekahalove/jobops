from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from jobops_api.db.models import Base, CandidateCompany, CandidateProfile, Company, JobListing, JobListingSource, JobSyncRun, Tenant
from jobops_api.job_discovery.ashby_utils import parse_ashby_job_board_url
from jobops_api.job_discovery.job_sync import sync_ashby_boards
from jobops_api.job_discovery.job_sync.ashby_service import resolve_ashby_board_sync_targets
from jobops_api.job_discovery.job_sync.providers.ashby import AshbyJobBoardClient, dedupe_ashby_board_sync_targets
from jobops_api.job_discovery.job_sync.providers.ashby.client import extract_ashby_jobs
from jobops_api.settings import Settings


def test_ashby_board_url_parser_accepts_common_shapes() -> None:
    board = parse_ashby_job_board_url("https://jobs.ashbyhq.com/hightouch")
    application = parse_ashby_job_board_url("https://jobs.ashbyhq.com/hightouch/application?utm=1")
    job = parse_ashby_job_board_url("https://jobs.ashbyhq.com/hightouch/job-123/?utm=1")

    assert board is not None
    assert board.org_slug == "hightouch"
    assert board.job_id is None
    assert board.canonical_board_url == "https://jobs.ashbyhq.com/hightouch"
    assert application is not None
    assert application.org_slug == "hightouch"
    assert application.job_id is None
    assert job is not None
    assert job.org_slug == "hightouch"
    assert job.job_id == "job-123"


def test_ashby_board_url_parser_rejects_non_ashby_urls() -> None:
    assert parse_ashby_job_board_url("https://jobs.lever.co/example/1") is None
    assert parse_ashby_job_board_url("https://example.com/jobs") is None
    assert parse_ashby_job_board_url("") is None


def test_ashby_client_fetches_public_board_jobs(monkeypatch) -> None:
    requested_urls: list[str] = []

    def fake_fetch_json(url: str):
        requested_urls.append(url)
        return {"jobs": [ashby_job_payload(job_id="job-1", title="Ashby Engineer")]}

    monkeypatch.setattr("jobops_api.job_discovery.job_sync.providers.ashby.client.fetch_json", fake_fetch_json)

    result = AshbyJobBoardClient().list_board_jobs("acme")

    assert requested_urls == ["https://api.ashbyhq.com/posting-api/job-board/acme"]
    assert result.valid is True
    assert result.provider_job_ids == ("job-1",)
    assert extract_ashby_jobs({"data": {"jobs": []}}) == []


def test_ashby_client_malformed_response_returns_diagnostic_failure(monkeypatch) -> None:
    monkeypatch.setattr("jobops_api.job_discovery.job_sync.providers.ashby.client.fetch_json", lambda url: {"oops": []})
    client = AshbyJobBoardClient()

    result = client.list_board_jobs("acme")
    diagnostics = client.diagnostics_json(org_slug="acme")

    assert result.valid is False
    assert "jobs array" in (result.error or "")
    assert diagnostics["listJobsResponseValid"] is False
    assert diagnostics["errorSummary"] == result.error


def test_explicit_ashby_board_sync_creates_job_listing_and_source(monkeypatch, tmp_path: Path) -> None:
    engine = create_engine_for_ashby_sync_tests()
    monkeypatch_ashby_payload(monkeypatch, {"jobs": [ashby_job_payload(job_id="job-1", title="Product Marketing Manager")]})

    with Session(engine) as session:
        result = sync_ashby_boards(
            session,
            settings=ashby_sync_settings(tmp_path),
            board_urls=["https://jobs.ashbyhq.com/acme"],
            include_configured=False,
            force=True,
        )[0]
        listing = session.scalar(select(JobListing))
        source = session.scalar(select(JobListingSource))
        run = session.scalar(select(JobSyncRun))

    assert result.status == "completed"
    assert result.raw_result_count == 1
    assert result.normalized_count == 1
    assert result.created_count == 1
    assert listing is not None
    assert listing.title == "Product Marketing Manager"
    assert listing.company_name == "Acme"
    assert source is not None
    assert source.source_provider == "ashby"
    assert source.provider_type == "ats_board"
    assert source.ats_provider == "ashby"
    assert source.ats_board_token == "acme"
    assert source.provider_job_id == "acme:job-1"
    assert source.raw_metadata_json["id"] == "job-1"
    assert source.raw_metadata_json["ashbyProviderJobId"] == "job-1"
    assert run is not None
    assert run.status == "completed"
    assert run.criteria_json["orgSlug"] == "acme"
    assert run.criteria_json["listJobsRawCount"] == 1


def test_ashby_sync_dedupes_board_urls_and_prefers_company_metadata(tmp_path: Path) -> None:
    engine = create_engine_for_ashby_sync_tests()
    with Session(engine) as session:
        tenant = Tenant(slug="tenant", name="Tenant")
        profile = CandidateProfile(tenant=tenant, slug="profile", display_name="Profile", headline="H", summary="S")
        company = Company(name="Acme", normalized_name="acme", ashby_board_url="https://jobs.ashbyhq.com/acme/job-1")
        session.add_all([profile, company])
        session.flush()
        session.add(CandidateCompany(candidate_profile_id=profile.id, company_id=company.id))
        session.commit()

        targets = resolve_ashby_board_sync_targets(
            session,
            settings=ashby_sync_settings(tmp_path),
            candidate_profile_id=profile.id,
            board_urls=["https://jobs.ashbyhq.com/acme"],
            include_configured=False,
        )

    deduped = dedupe_ashby_board_sync_targets(targets)
    assert len(deduped) == 1
    assert deduped[0].org_slug == "acme"
    assert deduped[0].company_id == company.id
    assert deduped[0].company_name == "Acme"


def test_failed_ashby_board_sync_records_failed_run(monkeypatch, tmp_path: Path) -> None:
    engine = create_engine_for_ashby_sync_tests()
    monkeypatch_ashby_payload(monkeypatch, {"unexpected": []})

    with Session(engine) as session:
        result = sync_ashby_boards(
            session,
            settings=ashby_sync_settings(tmp_path),
            board_urls=["https://jobs.ashbyhq.com/acme"],
            include_configured=False,
            force=True,
        )[0]
        session.commit()

    with Session(engine) as session:
        run = session.scalar(select(JobSyncRun))
        listings = session.scalars(select(JobListing)).all()

    assert result.status == "failed"
    assert "jobs array" in (result.error or "")
    assert run is not None
    assert run.status == "failed"
    assert run.criteria_json["listJobsResponseValid"] is False
    assert listings == []


def ashby_job_payload(*, job_id: str, title: str) -> dict[str, object]:
    return {
        "id": job_id,
        "title": title,
        "jobUrl": f"https://jobs.ashbyhq.com/acme/{job_id}",
        "locationName": "Remote US",
        "descriptionHtml": "<p>Build useful hiring workflows.</p>",
        "employmentType": "Full-time",
        "publishedAt": "2026-06-01T12:00:00Z",
    }


def monkeypatch_ashby_payload(monkeypatch, payload: dict[str, object]) -> None:
    monkeypatch.setattr("jobops_api.job_discovery.job_sync.providers.ashby.client.fetch_json", lambda url: payload)


def create_engine_for_ashby_sync_tests():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def ashby_sync_settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env="test",
        repo_root=tmp_path,
        database_url=None,
        model_provider="mock",
        company_discovery_search_grounding_enabled=True,
        default_model="mock-default",
        cheap_model="mock-cheap",
        gemini_api_key=None,
        profile_intake_save_artifacts=False,
        profile_intake_save_raw_text=False,
        ashby_board_urls=(),
    )
