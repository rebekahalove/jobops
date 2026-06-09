from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from jobops_api.db.models import (
    Application,
    Base,
    CandidateProfile,
    CandidateSavedJob,
    JobListing,
    JobListingSource,
    JobPosting,
    JobSyncRun,
    Tenant,
)
from jobops_api.job_discovery.job_sync import (
    JobListingSourceRecord,
    JobSyncRequest,
    JobSyncResult,
    NormalizedJobListing,
    build_adzuna_sync_key,
    build_greenhouse_sync_key,
    compute_url_fingerprint,
    is_sync_fresh,
    normalize_job_sync_location,
    record_job_sync_run,
    upsert_job_listing_from_provider_record,
)


def test_greenhouse_same_board_and_provider_job_id_updates_existing_listing() -> None:
    engine = create_engine_for_job_sync_tests()
    with Session(engine) as session:
        first = upsert_job_listing_from_provider_record(
            session,
            listing=listing(title="Applied AI Engineer"),
            source=greenhouse_source(provider_job_id="123", board_token="anthropic"),
        )
        second = upsert_job_listing_from_provider_record(
            session,
            listing=listing(title="Senior Applied AI Engineer"),
            source=greenhouse_source(provider_job_id="123", board_token="anthropic"),
        )

        assert first.created is True
        assert second.updated is True
        assert session.scalar(select(JobListing).where(JobListing.id == first.job_listing_id)).title == "Senior Applied AI Engineer"
        assert len(session.scalars(select(JobListing)).all()) == 1
        assert len(session.scalars(select(JobListingSource)).all()) == 1


def test_greenhouse_distinct_provider_job_ids_preserve_distinct_same_title_jobs() -> None:
    engine = create_engine_for_job_sync_tests()
    with Session(engine) as session:
        upsert_job_listing_from_provider_record(
            session,
            listing=listing(title="Applied AI Engineer", location_display="Remote US"),
            source=greenhouse_source(provider_job_id="123", board_token="anthropic"),
        )
        upsert_job_listing_from_provider_record(
            session,
            listing=listing(title="Applied AI Engineer", location_display="Remote US"),
            source=greenhouse_source(provider_job_id="456", board_token="anthropic"),
        )

        assert len(session.scalars(select(JobListing)).all()) == 2
        assert len(session.scalars(select(JobListingSource)).all()) == 2


def test_adzuna_same_provider_job_id_updates_existing_listing() -> None:
    engine = create_engine_for_job_sync_tests()
    with Session(engine) as session:
        first = upsert_job_listing_from_provider_record(
            session,
            listing=listing(title="AI Platform Engineer"),
            source=adzuna_source(provider_job_id="adz-1"),
        )
        second = upsert_job_listing_from_provider_record(
            session,
            listing=listing(title="Staff AI Platform Engineer"),
            source=adzuna_source(provider_job_id="adz-1"),
        )

        assert first.job_listing_id == second.job_listing_id
        assert second.updated is True
        assert len(session.scalars(select(JobListing)).all()) == 1


def test_adzuna_similar_jobs_with_different_provider_ids_do_not_merge() -> None:
    engine = create_engine_for_job_sync_tests()
    with Session(engine) as session:
        upsert_job_listing_from_provider_record(
            session,
            listing=listing(title="Applied AI Engineer", company_name="Acme AI", location_display="London, UK"),
            source=adzuna_source(provider_job_id="adz-1"),
        )
        upsert_job_listing_from_provider_record(
            session,
            listing=listing(title="Applied AI Engineer", company_name="Acme AI", location_display="London, UK"),
            source=adzuna_source(provider_job_id="adz-2"),
        )

        assert len(session.scalars(select(JobListing)).all()) == 2


def test_url_fingerprint_fallback_is_used_only_when_provider_id_is_absent() -> None:
    engine = create_engine_for_job_sync_tests()
    source_url = "https://jobs.example.test/postings/42?utm_source=newsletter"
    same_source_url = "http://jobs.example.test/postings/42"
    with Session(engine) as session:
        first = upsert_job_listing_from_provider_record(
            session,
            listing=listing(title="Fallback Identity Engineer"),
            source=adzuna_source(provider_job_id=None, source_url=source_url),
        )
        second = upsert_job_listing_from_provider_record(
            session,
            listing=listing(title="Fallback Identity Engineer Updated"),
            source=adzuna_source(provider_job_id=None, source_url=same_source_url),
        )
        third = upsert_job_listing_from_provider_record(
            session,
            listing=listing(title="Provider ID Wins Engineer"),
            source=adzuna_source(provider_job_id="adz-42", source_url=same_source_url),
        )

        assert first.job_listing_id == second.job_listing_id
        assert third.job_listing_id != first.job_listing_id
        assert compute_url_fingerprint(source_url) == compute_url_fingerprint(same_source_url)
        assert len(session.scalars(select(JobListing)).all()) == 2


def test_sync_freshness_counts_only_recent_completed_runs() -> None:
    engine = create_engine_for_job_sync_tests()
    sync_key = build_greenhouse_sync_key("anthropic")
    now = datetime.now(UTC)
    with Session(engine) as session:
        session.add(
            JobSyncRun(
                sync_key=sync_key,
                provider_name="greenhouse",
                provider_type="ats_board",
                sync_kind="company_board",
                status="failed",
                started_at=now - timedelta(hours=1),
                completed_at=now - timedelta(hours=1),
            )
        )
        session.commit()
        assert is_sync_fresh(session, sync_key) is False

        session.add(
            JobSyncRun(
                sync_key=sync_key,
                provider_name="greenhouse",
                provider_type="ats_board",
                sync_kind="company_board",
                status="completed",
                started_at=now - timedelta(hours=25),
                completed_at=now - timedelta(hours=25),
            )
        )
        session.commit()
        assert is_sync_fresh(session, sync_key) is False

        session.add(
            JobSyncRun(
                sync_key=sync_key,
                provider_name="greenhouse",
                provider_type="ats_board",
                sync_kind="company_board",
                status="completed",
                started_at=now - timedelta(hours=2),
                completed_at=now - timedelta(hours=2),
            )
        )
        session.commit()
        assert is_sync_fresh(session, sync_key) is True


def test_sync_key_construction_and_location_normalization() -> None:
    assert build_greenhouse_sync_key("Anthropic/") == "greenhouse:board:anthropic"
    assert build_adzuna_sync_key("GB", "London", "Applied AI Engineer") == "adzuna:broad:gb:london:applied-ai-engineer"

    remote_us = normalize_job_sync_location("Remote US")
    remote_uk = normalize_job_sync_location("Remote UK")
    louisville = normalize_job_sync_location("Louisville, KY")
    london = normalize_job_sync_location("London, UK")

    assert remote_us.provider_country == "us"
    assert remote_us.provider_where is None
    assert remote_uk.provider_country == "gb"
    assert louisville.provider_country == "us"
    assert louisville.provider_where == "Louisville, Kentucky"
    assert london.provider_country == "gb"
    assert london.provider_where == "London"


def test_record_job_sync_run_stores_request_diagnostics_without_secrets() -> None:
    engine = create_engine_for_job_sync_tests()
    with Session(engine) as session:
        run = record_job_sync_run(
            session,
            JobSyncResult(
                request=JobSyncRequest(
                    sync_key=build_adzuna_sync_key("us", "remote-us", "Applied AI Engineer"),
                    provider_name="adzuna",
                    provider_type="broad_search",
                    sync_kind="broad_search",
                    provider_country="us",
                    display_location="Remote US",
                    query_text="Applied AI Engineer",
                    criteria_json={
                        "apiPath": "/v1/api/jobs/us/search/1",
                        "what": "Applied AI Engineer",
                        "where": None,
                        "app_id": "secret-app-id",
                        "app_key": "secret-app-key",
                    },
                ),
                raw_result_count=10,
                normalized_count=9,
                created_count=8,
                updated_count=1,
            ),
        )

        assert run.criteria_json == {
            "apiPath": "/v1/api/jobs/us/search/1",
            "what": "Applied AI Engineer",
            "where": None,
        }


def test_job_sync_models_do_not_break_existing_applied_application_relationships() -> None:
    engine = create_engine_for_job_sync_tests()
    with Session(engine) as session:
        tenant = Tenant(name="Tenant", slug="tenant")
        profile = CandidateProfile(
            tenant=tenant,
            slug="candidate",
            display_name="Candidate",
            headline="Applied AI Engineer",
            summary="",
            profile_status="draft",
        )
        posting = JobPosting(
            title="Applied AI Engineer",
            company_name="Acme AI",
            job_url="https://jobs.example.test/1",
            normalized_url="https://jobs.example.test/1",
            source="manual",
        )
        saved_job = CandidateSavedJob(candidate_profile=profile, job=posting, status="saved")
        application = Application(
            candidate_profile=profile,
            job=posting,
            saved_job=saved_job,
            company_name="Acme AI",
            job_title="Applied AI Engineer",
            job_url="https://jobs.example.test/1",
            status="applied",
            date_applied=date(2026, 6, 1),
        )
        session.add(application)
        session.commit()

        loaded = session.scalar(select(Application).where(Application.id == application.id))
        assert loaded is not None
        assert loaded.job.id == posting.id
        assert loaded.saved_job.id == saved_job.id
        assert loaded.status == "applied"


def create_engine_for_job_sync_tests():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def listing(
    *,
    title: str,
    company_name: str = "Acme AI",
    location_display: str = "Remote US",
) -> NormalizedJobListing:
    return NormalizedJobListing(
        title=title,
        company_name=company_name,
        canonical_url="https://jobs.example.test/default",
        apply_url="https://jobs.example.test/default",
        source_url="https://jobs.example.test/default",
        location_raw=location_display,
        location_display=location_display,
        location_country="US",
        remote_work_mode="remote",
        employment_type="full_time",
        source_updated_at=datetime.now(UTC),
        source_status="active",
    )


def greenhouse_source(*, provider_job_id: str, board_token: str) -> JobListingSourceRecord:
    return JobListingSourceRecord(
        source_provider="greenhouse",
        provider_type="ats_board",
        provider_job_id=provider_job_id,
        source_result_id=f"{board_token}:{provider_job_id}",
        ats_provider="greenhouse",
        ats_board_token=board_token,
        source_url=f"https://boards.greenhouse.io/{board_token}/jobs/{provider_job_id}",
        apply_url=f"https://boards.greenhouse.io/{board_token}/jobs/{provider_job_id}",
        canonical_url=f"https://boards.greenhouse.io/{board_token}/jobs/{provider_job_id}",
        raw_metadata_json={"id": provider_job_id},
        source_status="active",
    )


def adzuna_source(*, provider_job_id: str | None, source_url: str | None = None) -> JobListingSourceRecord:
    return JobListingSourceRecord(
        source_provider="adzuna",
        provider_type="broad_search",
        provider_job_id=provider_job_id,
        source_result_id=provider_job_id,
        source_url=source_url or f"https://adzuna.example.test/jobs/{provider_job_id or 'fallback'}",
        apply_url=source_url or f"https://adzuna.example.test/jobs/{provider_job_id or 'fallback'}",
        canonical_url=source_url or f"https://adzuna.example.test/jobs/{provider_job_id or 'fallback'}",
        source_query="Applied AI Engineer",
        source_country="us",
        raw_metadata_json={"id": provider_job_id},
        source_status="active",
    )
