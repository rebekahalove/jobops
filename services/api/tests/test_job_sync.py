from __future__ import annotations

import urllib.error
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from jobops_api.db.models import (
    Application,
    Base,
    CandidateCompany,
    CandidateProfile,
    CandidateSavedJob,
    Company,
    JobListing,
    JobListingSource,
    JobLocationTarget,
    JobProviderLocationMapping,
    JobPosting,
    JobSyncRun,
    Tenant,
)
from jobops_api.job_discovery.job_sync import (
    BaseJobSyncProvider,
    JobListingSourceRecord,
    JobSyncRequest,
    JobSyncResult,
    NormalizedJobListing,
    build_adzuna_sync_key,
    build_greenhouse_sync_key,
    is_sync_fresh,
    normalize_location_key,
    record_job_sync_run,
    resolve_greenhouse_board_sync_targets,
    resolve_provider_location_mapping,
    sync_greenhouse_boards,
    upsert_job_listing_from_provider_record,
)
import jobops_api.cli as cli_module
import jobops_api.job_discovery.job_sync as job_sync_module
import jobops_api.job_discovery.job_sync.models as job_sync_models
from jobops_api.job_discovery.job_sync.providers.adzuna import AdzunaJobSyncProvider
from jobops_api.job_discovery.job_sync.providers.greenhouse import GreenhouseBoardSyncTarget, GreenhouseJobSyncProvider
from jobops_api.settings import Settings


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
        assert len(session.scalars(select(CandidateSavedJob)).all()) == 0


def test_job_sync_upsert_never_creates_candidate_saved_jobs() -> None:
    engine = create_engine_for_job_sync_tests()
    with Session(engine) as session:
        result = upsert_job_listing_from_provider_record(
            session,
            listing=listing(title="Synced Inventory Only"),
            source=greenhouse_source(provider_job_id="inventory-only", board_token="anthropic"),
        )
        session.commit()

        saved_links = list(session.scalars(select(CandidateSavedJob)).all())
        synced_listing = session.get(JobListing, result.job_listing_id)

    assert synced_listing is not None
    assert saved_links == []


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


def test_job_listing_upsert_preserves_provider_title_longer_than_240_characters() -> None:
    long_title = (
        "Senior AI & Data Analytics Architect - Atlanta GA, Hybrid(3 days Onsite). In-person is mandatory and "
        "preferred only locals. Must have strong experience in Python, SQL, Machine Learning, Deep Learning, NLP, "
        "Generative AI, GPT, Claude, Gemini, Llama, Mistral, governance, monitoring, and analytics platforms"
    )
    assert len(long_title) > 240
    engine = create_engine_for_job_sync_tests()

    with Session(engine) as session:
        result = upsert_job_listing_from_provider_record(
            session,
            listing=listing(title=long_title),
            source=greenhouse_source(provider_job_id="long-title-1", board_token="long-title-board"),
        )
        stored = session.get(JobListing, result.job_listing_id)

        assert stored is not None
        assert stored.title == long_title


def test_greenhouse_fetches_retrieve_job_payload_with_application_questions(monkeypatch) -> None:
    requested: list[tuple[str, dict[str, object] | None]] = []
    list_job = greenhouse_list_job_raw()
    retrieve_job = greenhouse_retrieve_job_raw()

    def fake_fetch_json(url: str, *, params: dict[str, object] | None = None):
        requested.append((url, params))
        if url.endswith("/jobs"):
            return {"jobs": [list_job], "meta": {"total": 1}}
        if url.endswith("/jobs/44444"):
            return retrieve_job
        raise AssertionError(f"Unexpected Greenhouse URL: {url}")

    monkeypatch.setattr("jobops_api.job_discovery.job_sync.providers.greenhouse.client.fetch_json", fake_fetch_json)
    provider = GreenhouseJobSyncProvider()
    request = provider.build_sync_plan(["vaulttec"]).requests[0]

    records = list(provider.fetch_provider_records(request))

    assert records == [
        {
            **list_job,
            **retrieve_job,
            "job_board_list_payload": list_job,
            "job_board_retrieve_payload": retrieve_job,
            "job_board_retrieve_request": greenhouse_retrieve_request("vaulttec", "44444"),
        }
    ]
    assert requested == [
        ("https://boards-api.greenhouse.io/v1/boards/vaulttec/jobs", {"content": "true"}),
        (
            "https://boards-api.greenhouse.io/v1/boards/vaulttec/jobs/44444",
            {"questions": "true", "pay_transparency": "true"},
        ),
    ]
    assert request.criteria_json["retrieveJobQuestions"] is True
    assert request.criteria_json["retrieveJobPayTransparency"] is True


def test_greenhouse_source_record_retains_list_and_retrieve_job_fields() -> None:
    provider = GreenhouseJobSyncProvider()
    request = provider.build_sync_plan(["vaulttec"]).requests[0]
    raw = {
        **greenhouse_list_job_raw(),
        **greenhouse_retrieve_job_raw(),
        "job_board_list_payload": greenhouse_list_job_raw(),
        "job_board_retrieve_payload": greenhouse_retrieve_job_raw(),
        "job_board_retrieve_request": greenhouse_retrieve_request("vaulttec", "44444"),
    }
    engine = create_engine_for_job_sync_tests()

    with Session(engine) as session:
        normalized = provider.normalize_provider_record(raw, request, session=session)
        assert normalized is not None
        target = session.get(JobLocationTarget, normalized[0].job_location_target_id)
        assert target is not None
        assert target.display_name == "San Francisco, CA"
        assert target.confidence == "low"
        assert target.verification_status == "needs_review"

    assert normalized is not None
    listing_record, source = normalized
    assert listing_record.title == "Product Engineer"
    assert listing_record.job_location_target_id is not None
    assert source.source_provider == "greenhouse"
    assert source.provider_job_id == "44444"
    assert source.source_result_id == "vaulttec:44444"
    assert source.raw_metadata_json == raw
    assert source.raw_metadata_json["internal_job_id"] == 55555
    assert source.raw_metadata_json["requisition_id"] == "50"
    assert source.raw_metadata_json["language"] == "en"
    assert source.raw_metadata_json["metadata"] == [{"id": 12345, "name": "Field Name", "value_type": "text", "value": "Some value"}]
    assert source.raw_metadata_json["departments"] == greenhouse_list_job_raw()["departments"]
    assert source.raw_metadata_json["offices"] == greenhouse_list_job_raw()["offices"]
    assert source.raw_metadata_json["questions"][1]["label"] == "Resume"
    assert source.raw_metadata_json["location_questions"][0]["label"] == "Location"
    assert source.raw_metadata_json["compliance"][0]["label"] == "Veteran Status"
    assert source.raw_metadata_json["data_compliance"][0]["type"] == "gdpr"
    assert source.raw_metadata_json["demographic_questions"]["questions"][0]["label"] == "Favorite Color"
    assert source.raw_metadata_json["pay_input_ranges"][0]["currency_type"] == "USD"
    assert source.raw_metadata_json["job_board_retrieve_request"] == greenhouse_retrieve_request("vaulttec", "44444")


def test_greenhouse_provider_location_creates_reviewable_target_without_us_default() -> None:
    provider = GreenhouseJobSyncProvider()
    request = provider.build_sync_plan(["vaulttec"]).requests[0]
    raw = {
        **greenhouse_list_job_raw(),
        "location": {"name": "Moon Base Alpha"},
    }
    engine = create_engine_for_job_sync_tests()

    with Session(engine) as session:
        normalized = provider.normalize_provider_record(raw, request, session=session)
        assert normalized is not None
        target = session.get(JobLocationTarget, normalized[0].job_location_target_id)
        assert target is not None
        assert target.display_name == "Moon Base Alpha"
        assert target.normalized_key == "moon-base-alpha"
        assert target.country_code is None
        assert target.confidence == "low"
        assert target.verification_status == "needs_review"
        assert normalized[0].location_raw == "Moon Base Alpha"


def test_greenhouse_detail_failure_keeps_list_job_and_records_diagnostics(monkeypatch) -> None:
    requested: list[tuple[str, dict[str, object] | None]] = []
    first_list_job = greenhouse_list_job_raw(job_id=44444, title="Product Engineer")
    second_list_job = greenhouse_list_job_raw(job_id=55555, title="Data Engineer")
    first_detail = greenhouse_retrieve_job_raw(job_id=44444, title="Product Engineer")

    def fake_fetch_json(url: str, *, params: dict[str, object] | None = None):
        requested.append((url, params))
        if url.endswith("/jobs"):
            return {"jobs": [first_list_job, second_list_job], "meta": {"total": 2}}
        if url.endswith("/jobs/44444"):
            return first_detail
        if url.endswith("/jobs/55555"):
            raise urllib.error.HTTPError(url, 404, "Not Found", hdrs=None, fp=None)
        raise AssertionError(f"Unexpected Greenhouse URL: {url}")

    monkeypatch.setattr("jobops_api.job_discovery.job_sync.providers.greenhouse.client.fetch_json", fake_fetch_json)
    provider = GreenhouseJobSyncProvider()
    request = provider.build_sync_plan(["vaulttec"]).requests[0]
    engine = create_engine_for_job_sync_tests()

    with Session(engine) as session:
        result = provider.refresh_inventory(session, request, freshness_hours=0)
        sources = session.scalars(select(JobListingSource).order_by(JobListingSource.provider_job_id)).all()
        run = session.scalar(select(JobSyncRun))

    assert result.raw_result_count == 2
    assert result.normalized_count == 2
    assert result.created_count == 2
    assert result.diagnostics_json == {
        "detailRequestsAttempted": 2,
        "detailRequestsSucceeded": 1,
        "detailRequestsFailed": 1,
        "detailRequestsSkippedByGuardrail": 0,
        "listJobsResponseValid": True,
    }
    assert run is not None
    assert run.criteria_json["detailRequestsAttempted"] == 2
    assert run.criteria_json["detailRequestsSucceeded"] == 1
    assert run.criteria_json["detailRequestsFailed"] == 1
    assert len(sources) == 2
    failed_source = next(source for source in sources if source.provider_job_id == "55555")
    assert failed_source.raw_metadata_json["job_board_list_payload"] == second_list_job
    assert failed_source.raw_metadata_json["job_board_retrieve_payload"] is None
    assert failed_source.raw_metadata_json["job_board_retrieve_request"] == greenhouse_retrieve_request("vaulttec", "55555")
    assert failed_source.raw_metadata_json["job_board_retrieve_error"] == {
        "type": "HTTPError",
        "message": "Greenhouse retrieve-job request failed.",
        "status": 404,
    }
    assert requested == [
        ("https://boards-api.greenhouse.io/v1/boards/vaulttec/jobs", {"content": "true"}),
        ("https://boards-api.greenhouse.io/v1/boards/vaulttec/jobs/44444", {"questions": "true", "pay_transparency": "true"}),
        ("https://boards-api.greenhouse.io/v1/boards/vaulttec/jobs/55555", {"questions": "true", "pay_transparency": "true"}),
    ]


def test_greenhouse_detail_max_guardrail_keeps_list_jobs(monkeypatch) -> None:
    requested: list[tuple[str, dict[str, object] | None]] = []
    first_list_job = greenhouse_list_job_raw(job_id=44444, title="Product Engineer")
    second_list_job = greenhouse_list_job_raw(job_id=55555, title="Data Engineer")

    def fake_fetch_json(url: str, *, params: dict[str, object] | None = None):
        requested.append((url, params))
        if url.endswith("/jobs"):
            return {"jobs": [first_list_job, second_list_job], "meta": {"total": 2}}
        if url.endswith("/jobs/44444"):
            return greenhouse_retrieve_job_raw(job_id=44444, title="Product Engineer")
        raise AssertionError(f"Unexpected Greenhouse detail fetch beyond guardrail: {url}")

    monkeypatch.setattr("jobops_api.job_discovery.job_sync.providers.greenhouse.client.fetch_json", fake_fetch_json)
    provider = GreenhouseJobSyncProvider(max_detail_requests=1)
    request = provider.build_sync_plan(["vaulttec"]).requests[0]
    engine = create_engine_for_job_sync_tests()

    with Session(engine) as session:
        result = provider.refresh_inventory(session, request, freshness_hours=0)
        sources = session.scalars(select(JobListingSource).order_by(JobListingSource.provider_job_id)).all()
        run = session.scalar(select(JobSyncRun))

    assert result.normalized_count == 2
    assert result.diagnostics_json == {
        "detailRequestsAttempted": 1,
        "detailRequestsSucceeded": 1,
        "detailRequestsFailed": 0,
        "detailRequestsSkippedByGuardrail": 1,
        "listJobsResponseValid": True,
    }
    assert run is not None
    assert run.criteria_json["maxDetailRequests"] == 1
    assert run.criteria_json["detailRequestsSkippedByGuardrail"] == 1
    assert len(sources) == 2
    skipped_source = next(source for source in sources if source.provider_job_id == "55555")
    assert skipped_source.raw_metadata_json["job_board_retrieve_payload"] is None
    assert skipped_source.raw_metadata_json["job_board_retrieve_request"] == greenhouse_retrieve_request("vaulttec", "55555")
    assert skipped_source.raw_metadata_json["job_board_retrieve_skipped"] == {
        "reason": "max_detail_requests_reached",
        "maxDetailRequests": 1,
    }
    assert requested == [
        ("https://boards-api.greenhouse.io/v1/boards/vaulttec/jobs", {"content": "true"}),
        ("https://boards-api.greenhouse.io/v1/boards/vaulttec/jobs/44444", {"questions": "true", "pay_transparency": "true"}),
    ]


def test_greenhouse_sync_plan_accepts_company_targets_and_dedupes_tokens() -> None:
    provider = GreenhouseJobSyncProvider()

    plan = provider.build_sync_plan(
        [
            GreenhouseBoardSyncTarget(
                board_token="vaulttec",
                company_id="company-1",
                company_name="Vault-Tec",
                source="configured_company_board_token",
            ),
            "vaulttec",
        ]
    )

    assert len(plan.requests) == 1
    request = plan.requests[0]
    assert request.sync_key == "greenhouse:board:vaulttec"
    assert request.company_id == "company-1"
    assert request.company_name == "Vault-Tec"
    assert request.criteria_json["targetSource"] == "configured_company_board_token"


def test_greenhouse_sync_service_syncs_full_board(monkeypatch) -> None:
    engine = create_engine_for_job_sync_tests()
    requested = install_greenhouse_fetch_mock(
        monkeypatch,
        board_token="vaulttec",
        jobs=[
            greenhouse_list_job_raw(job_id=44444, title="Product Engineer"),
            greenhouse_list_job_raw(job_id=55555, title="Data Engineer"),
        ],
    )

    with Session(engine) as session:
        results = sync_greenhouse_boards(
            session,
            settings=job_sync_settings(greenhouse_board_tokens=("vaulttec",)),
            include_configured=True,
        )
        listings = session.scalars(select(JobListing).order_by(JobListing.title)).all()
        sources = session.scalars(select(JobListingSource).order_by(JobListingSource.provider_job_id)).all()
        run = session.scalar(select(JobSyncRun))

    assert len(results) == 1
    result = results[0]
    assert result.status == "completed"
    assert result.raw_result_count == 2
    assert result.normalized_count == 2
    assert result.created_count == 2
    assert result.closed_count == 0
    assert len(listings) == 2
    assert len(sources) == 2
    assert run is not None
    assert run.status == "completed"
    assert run.raw_result_count == 2
    assert run.criteria_json["apiUrl"] == "https://boards-api.greenhouse.io/v1/boards/vaulttec/jobs"
    assert run.criteria_json["retrieveJobQuestions"] is True
    assert run.criteria_json["retrieveJobPayTransparency"] is True
    assert run.criteria_json["detailRequestsAttempted"] == 2
    assert requested == [
        ("https://boards-api.greenhouse.io/v1/boards/vaulttec/jobs", {"content": "true"}),
        ("https://boards-api.greenhouse.io/v1/boards/vaulttec/jobs/44444", {"questions": "true", "pay_transparency": "true"}),
        ("https://boards-api.greenhouse.io/v1/boards/vaulttec/jobs/55555", {"questions": "true", "pay_transparency": "true"}),
    ]


def test_greenhouse_sync_service_counts_missing_job_id_as_failed_normalization(monkeypatch) -> None:
    engine = create_engine_for_job_sync_tests()
    missing_id_job = greenhouse_list_job_raw(job_id=55555, title="No Id Engineer")
    missing_id_job.pop("id")
    install_greenhouse_fetch_mock(
        monkeypatch,
        board_token="vaulttec",
        jobs=[greenhouse_list_job_raw(job_id=44444, title="Product Engineer"), missing_id_job],
    )

    with Session(engine) as session:
        result = sync_greenhouse_boards(
            session,
            settings=job_sync_settings(greenhouse_board_tokens=("vaulttec",)),
            include_configured=True,
        )[0]
        listings = session.scalars(select(JobListing)).all()
        sources = session.scalars(select(JobListingSource)).all()

    assert result.raw_result_count == 2
    assert result.normalized_count == 1
    assert result.failed_normalization_count == 1
    assert len(listings) == 1
    assert len(sources) == 1


def test_greenhouse_sync_service_respects_freshness(monkeypatch) -> None:
    engine = create_engine_for_job_sync_tests()
    requested = install_greenhouse_fetch_mock(
        monkeypatch,
        board_token="vaulttec",
        jobs=[greenhouse_list_job_raw(job_id=44444, title="Product Engineer")],
    )
    settings = job_sync_settings(greenhouse_board_tokens=("vaulttec",))

    with Session(engine) as session:
        first = sync_greenhouse_boards(session, settings=settings, include_configured=True)[0]

        def fail_if_called(url: str, *, params: dict[str, object] | None = None):
            raise AssertionError(f"Fresh sync should not call Greenhouse API: {url}")

        monkeypatch.setattr("jobops_api.job_discovery.job_sync.providers.greenhouse.client.fetch_json", fail_if_called)
        second = sync_greenhouse_boards(session, settings=settings, include_configured=True)[0]
        runs = session.scalars(select(JobSyncRun).order_by(JobSyncRun.created_at.asc())).all()
        fresh = is_sync_fresh(session, "greenhouse:board:vaulttec")

    assert first.status == "completed"
    assert second.status == "skipped_fresh"
    assert second.diagnostics_json["skipReason"] == "fresh"
    assert len(requested) == 2
    assert [run.status for run in runs] == ["completed", "skipped_fresh"]
    assert fresh is True


def test_greenhouse_sync_service_force_refresh_ignores_freshness(monkeypatch) -> None:
    engine = create_engine_for_job_sync_tests()
    settings = job_sync_settings(greenhouse_board_tokens=("vaulttec",))
    first_requested = install_greenhouse_fetch_mock(
        monkeypatch,
        board_token="vaulttec",
        jobs=[greenhouse_list_job_raw(job_id=44444, title="Product Engineer")],
    )

    with Session(engine) as session:
        first = sync_greenhouse_boards(session, settings=settings, include_configured=True)[0]
        second_requested = install_greenhouse_fetch_mock(
            monkeypatch,
            board_token="vaulttec",
            jobs=[greenhouse_list_job_raw(job_id=44444, title="Senior Product Engineer")],
        )
        second = sync_greenhouse_boards(session, settings=settings, include_configured=True, force=True)[0]
        listing = session.scalar(select(JobListing))

    assert first.status == "completed"
    assert second.status == "completed"
    assert len(first_requested) == 2
    assert len(second_requested) == 2
    assert listing is not None
    assert listing.title == "Senior Product Engineer"


def test_greenhouse_sync_service_preserves_company_metadata(monkeypatch) -> None:
    engine = create_engine_for_job_sync_tests()
    install_greenhouse_fetch_mock(
        monkeypatch,
        board_token="vaulttec",
        jobs=[greenhouse_list_job_raw(job_id=44444, title="Product Engineer")],
    )

    with Session(engine) as session:
        results = sync_greenhouse_boards(
            session,
            settings=job_sync_settings(greenhouse_company_boards={"Vault-Tec": "vaulttec"}),
            include_configured=True,
        )
        listing_record = session.scalar(select(JobListing))
        run = session.scalar(select(JobSyncRun))

    assert results[0].status == "completed"
    assert listing_record is not None
    assert listing_record.company_name == "Vault-Tec"
    assert run is not None
    assert run.company_name == "Vault-Tec"


def test_greenhouse_sync_service_marks_missing_jobs_closed_and_reactivates(monkeypatch) -> None:
    engine = create_engine_for_job_sync_tests()
    settings = job_sync_settings(greenhouse_board_tokens=("vaulttec",))

    with Session(engine) as session:
        install_greenhouse_fetch_mock(
            monkeypatch,
            board_token="vaulttec",
            jobs=[
                greenhouse_list_job_raw(job_id=1, title="One"),
                greenhouse_list_job_raw(job_id=2, title="Two"),
                greenhouse_list_job_raw(job_id=3, title="Three"),
            ],
        )
        first = sync_greenhouse_boards(session, settings=settings, include_configured=True, force=True)[0]

        install_greenhouse_fetch_mock(
            monkeypatch,
            board_token="vaulttec",
            jobs=[greenhouse_list_job_raw(job_id=1, title="One"), greenhouse_list_job_raw(job_id=3, title="Three")],
        )
        second = sync_greenhouse_boards(session, settings=settings, include_configured=True, force=True)[0]
        closed_source = session.scalar(select(JobListingSource).where(JobListingSource.provider_job_id == "2"))
        assert closed_source is not None
        closed_listing_id = closed_source.job_listing_id
        closed_listing = session.get(JobListing, closed_listing_id)
        closed_source_is_active = closed_source.is_active
        closed_source_reason = closed_source.close_reason
        closed_listing_is_active = closed_listing.is_active if closed_listing else None
        closed_listing_reason = closed_listing.close_reason if closed_listing else None

        install_greenhouse_fetch_mock(
            monkeypatch,
            board_token="vaulttec",
            jobs=[
                greenhouse_list_job_raw(job_id=1, title="One"),
                greenhouse_list_job_raw(job_id=2, title="Two Again"),
                greenhouse_list_job_raw(job_id=3, title="Three"),
            ],
        )
        third = sync_greenhouse_boards(session, settings=settings, include_configured=True, force=True)[0]
        reactivated_source = session.scalar(select(JobListingSource).where(JobListingSource.provider_job_id == "2"))
        reactivated_listing = session.get(JobListing, closed_listing_id)

    assert first.created_count == 3
    assert second.closed_count == 1
    assert closed_listing is not None
    assert closed_source_is_active is False
    assert closed_source_reason == "missing_from_latest_greenhouse_board_sync"
    assert closed_listing_is_active is False
    assert closed_listing_reason == "missing_from_latest_greenhouse_board_sync"
    assert third.updated_count == 3
    assert reactivated_source is not None
    assert reactivated_source.is_active is True
    assert reactivated_source.closed_at is None
    assert reactivated_listing is not None
    assert reactivated_listing.is_active is True
    assert reactivated_listing.closed_at is None


def test_greenhouse_failed_list_request_does_not_mark_jobs_closed(monkeypatch) -> None:
    engine = create_engine_for_job_sync_tests()
    settings = job_sync_settings(greenhouse_board_tokens=("vaulttec",))
    install_greenhouse_fetch_mock(
        monkeypatch,
        board_token="vaulttec",
        jobs=[greenhouse_list_job_raw(job_id=44444, title="Product Engineer")],
    )

    with Session(engine) as session:
        sync_greenhouse_boards(session, settings=settings, include_configured=True, force=True)

        def fail_list_jobs(url: str, *, params: dict[str, object] | None = None):
            raise urllib.error.HTTPError(url, 500, "Boom", hdrs=None, fp=None)

        monkeypatch.setattr("jobops_api.job_discovery.job_sync.providers.greenhouse.client.fetch_json", fail_list_jobs)
        result = sync_greenhouse_boards(session, settings=settings, include_configured=True, force=True)[0]
        source = session.scalar(select(JobListingSource))
        listing_record = session.scalar(select(JobListing))

    assert result.status == "failed"
    assert result.error is not None
    assert "HTTP Error 500" in result.error
    assert source is not None
    assert source.is_active is True
    assert source.closed_at is None
    assert listing_record is not None
    assert listing_record.is_active is True


def test_greenhouse_sync_target_resolution_includes_candidate_company_board() -> None:
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
        company = Company(
            name="Vault-Tec",
            normalized_name="vault tec",
            greenhouse_board_token="vaulttec",
        )
        session.add(CandidateCompany(candidate_profile=profile, company=company))
        session.flush()

        targets = resolve_greenhouse_board_sync_targets(
            session,
            settings=job_sync_settings(),
            candidate_profile_id=profile.id,
            include_configured=False,
        )

    assert targets == (
        GreenhouseBoardSyncTarget(
            board_token="vaulttec",
            company_id=company.id,
            company_name="Vault-Tec",
            source="candidate_company_board_token",
        ),
    )


def test_adzuna_same_provider_job_id_updates_existing_listing() -> None:
    engine = create_engine_for_job_sync_tests()
    provider = AdzunaJobSyncProvider()
    request = adzuna_sync_request()
    with Session(engine) as session:
        first_normalized = provider.normalize_provider_record(
            adzuna_raw(id="adz-1", title="AI Platform Engineer", redirect_url="https://adzuna.example.test/a?tracking=1"),
            request,
            session=session,
        )
        second_normalized = provider.normalize_provider_record(
            adzuna_raw(id="adz-1", title="Staff AI Platform Engineer", redirect_url="https://adzuna.example.test/b?tracking=2"),
            request,
            session=session,
        )
        assert first_normalized is not None
        assert second_normalized is not None
        first = upsert_job_listing_from_provider_record(
            session,
            listing=first_normalized[0],
            source=first_normalized[1],
        )
        second = upsert_job_listing_from_provider_record(
            session,
            listing=second_normalized[0],
            source=second_normalized[1],
        )

        assert first.job_listing_id == second.job_listing_id
        assert second.updated is True
        source = session.scalar(select(JobListingSource))
        assert source is not None
        assert source.source_provider == "adzuna"
        assert source.provider_job_id == "adz-1"
        assert source.source_result_id == "adz-1"
        assert len(session.scalars(select(JobListing)).all()) == 1


def test_adzuna_same_id_with_different_redirect_url_updates_same_listing() -> None:
    engine = create_engine_for_job_sync_tests()
    provider = AdzunaJobSyncProvider()
    request = adzuna_sync_request()
    with Session(engine) as session:
        first_normalized = provider.normalize_provider_record(
            adzuna_raw(id=99, redirect_url="https://adzuna.example.test/redirect?job=99&tracking=one"),
            request,
            session=session,
        )
        second_normalized = provider.normalize_provider_record(
            adzuna_raw(id=99, redirect_url="https://adzuna.example.test/redirect?job=99&tracking=two"),
            request,
            session=session,
        )
        assert first_normalized is not None
        assert second_normalized is not None

        first = upsert_job_listing_from_provider_record(session, listing=first_normalized[0], source=first_normalized[1])
        second = upsert_job_listing_from_provider_record(session, listing=second_normalized[0], source=second_normalized[1])

        assert first.job_listing_id == second.job_listing_id
        assert len(session.scalars(select(JobListing)).all()) == 1
        source = session.scalar(select(JobListingSource))
        assert source is not None
        assert source.provider_job_id == "99"
        assert source.source_result_id == "99"
        assert source.source_url == "https://adzuna.example.test/redirect?job=99&tracking=two"


def test_adzuna_source_record_retains_raw_api_response_fields() -> None:
    provider = AdzunaJobSyncProvider()
    request = adzuna_sync_request()
    engine = create_engine_for_job_sync_tests()
    raw = {
        "salary_is_predicted": "1",
        "created": "2026-06-03T09:44:54Z",
        "category": {
            "__CLASS__": "Adzuna::API::Response::Category",
            "tag": "healthcare-nursing-jobs",
            "label": "Healthcare & Nursing Jobs",
        },
        "redirect_url": "https://www.adzuna.com/land/ad/5750706638?se=Hnuptc5j8RGxEpABevI5bA&utm_medium=api&utm_source=eba7774e&v=2ED33E8F08AE7E2AD65CF6F23FE1D9958955A52A",
        "salary_min": 60680.7,
        "company": {
            "__CLASS__": "Adzuna::API::Response::Company",
            "display_name": "Mission Hospital",
        },
        "salary_max": 60680.7,
        "title": "Psych Emergency Room Registered Nurse",
        "adref": "eyJhbGciOiJIUzI1NiJ9.eyJpIjoiNTc1MDcwNjYzOCIsInMiOiJIbnVwdGM1ajhSR3hFcEFCZXZJNWJBIn0.6ZYmkcKaeRL0AY16rllVb7wMytXI7WMxwSqS2cSTETQ",
        "longitude": -82.555682,
        "__CLASS__": "Adzuna::API::Response::Job",
        "latitude": 35.596321,
        "description": "Do you have the career opportunities as a Psych ED Registered Nurse you want?",
        "location": {
            "display_name": "Asheville, Buncombe County",
            "area": ["US", "North Carolina", "Buncombe County", "Asheville"],
            "__CLASS__": "Adzuna::API::Response::Location",
        },
        "id": "5750706638",
    }

    with Session(engine) as session:
        normalized = provider.normalize_provider_record(raw, request, session=session)
        assert normalized is not None
        target = session.get(JobLocationTarget, normalized[0].job_location_target_id)
        assert target is not None
        assert target.normalized_key == "asheville-north-carolina-us"
        assert target.country_code == "US"

    assert normalized is not None
    listing_record, source = normalized
    assert listing_record.job_location_target_id is not None
    assert listing_record.location_city == "Asheville"
    assert listing_record.location_region == "North Carolina"
    assert listing_record.location_country == "US"
    assert listing_record.location_confidence == "medium"
    assert source.source_provider == "adzuna"
    assert source.provider_job_id == "5750706638"
    assert source.source_result_id == "5750706638"
    assert source.raw_metadata_json == raw


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


def test_greenhouse_same_provider_job_id_on_different_boards_does_not_merge() -> None:
    engine = create_engine_for_job_sync_tests()
    with Session(engine) as session:
        upsert_job_listing_from_provider_record(
            session,
            listing=listing(title="Applied AI Engineer", company_name="Acme AI", location_display="Remote US"),
            source=greenhouse_source(provider_job_id="123", board_token="company-a"),
        )
        upsert_job_listing_from_provider_record(
            session,
            listing=listing(title="Applied AI Engineer", company_name="Acme AI", location_display="Remote US"),
            source=greenhouse_source(provider_job_id="123", board_token="company-b"),
        )

        assert len(session.scalars(select(JobListing)).all()) == 2
        assert len(session.scalars(select(JobListingSource)).all()) == 2


def test_cross_provider_same_job_shape_does_not_merge() -> None:
    engine = create_engine_for_job_sync_tests()
    with Session(engine) as session:
        upsert_job_listing_from_provider_record(
            session,
            listing=listing(title="Applied AI Engineer", company_name="Acme AI", location_display="Remote US"),
            source=greenhouse_source(provider_job_id="123", board_token="acme"),
        )
        upsert_job_listing_from_provider_record(
            session,
            listing=listing(title="Applied AI Engineer", company_name="Acme AI", location_display="Remote US"),
            source=adzuna_source(provider_job_id="123"),
        )

        assert len(session.scalars(select(JobListing)).all()) == 2
        assert len(session.scalars(select(JobListingSource)).all()) == 2


def test_provider_record_without_id_is_rejected_without_url_identity() -> None:
    engine = create_engine_for_job_sync_tests()
    source_url = "https://jobs.example.test/postings/42?utm_source=newsletter"
    with Session(engine) as session:
        with pytest.raises(ValueError, match="stable provider job id"):
            upsert_job_listing_from_provider_record(
                session,
                listing=listing(title="No Identity Engineer"),
                source=generic_source(provider_job_id=None, source_url=source_url),
            )

        assert session.scalars(select(JobListing)).all() == []


def test_adzuna_record_without_id_is_failed_normalization() -> None:
    engine = create_engine_for_job_sync_tests()
    provider = AdzunaJobSyncProvider()
    request = adzuna_sync_request()
    raw_without_id = adzuna_raw(id=None, redirect_url="https://adzuna.example.test/redirect?job=missing&tracking=one")
    raw_without_id.pop("id")

    class MissingIdAdzunaProvider(AdzunaJobSyncProvider):
        def fetch_provider_records(self, request: JobSyncRequest):
            return [raw_without_id]

    with Session(engine) as session:
        assert provider.normalize_provider_record(raw_without_id, request, session=session) is None
        result = MissingIdAdzunaProvider().refresh_inventory(session, request)

        assert result.raw_result_count == 1
        assert result.normalized_count == 0
        assert result.failed_normalization_count == 1
        assert session.scalars(select(JobListing)).all() == []


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


def test_refresh_inventory_records_skipped_fresh_without_defining_freshness() -> None:
    class OneRecordProvider(BaseJobSyncProvider):
        provider_name = "test_provider"
        provider_type = "broad_search"

        def build_sync_plan(self):
            return None

        def fetch_provider_records(self, request: JobSyncRequest):
            return [{"id": "sync-1"}]

        def normalize_provider_record(self, raw: object, request: JobSyncRequest, *, session: Session):
            return (
                listing(title="Applied AI Engineer"),
                JobListingSourceRecord(
                    source_provider=self.provider_name,
                    provider_type=self.provider_type,
                    provider_job_id="sync-1",
                    source_result_id="sync-1",
                    source_url="https://provider.example.test/jobs/sync-1",
                    raw_metadata_json={"id": "sync-1"},
                    source_status="active",
                ),
            )

    engine = create_engine_for_job_sync_tests()
    request = JobSyncRequest(
        sync_key="test-provider:broad:remote-us:applied-ai-engineer",
        provider_name="test_provider",
        provider_type="broad_search",
        sync_kind="broad_search",
        criteria_json={"apiPath": "/jobs/search", "what": "Applied AI Engineer"},
    )
    provider = OneRecordProvider()
    with Session(engine) as session:
        first = provider.refresh_inventory(session, request)
        second = provider.refresh_inventory(session, request, freshness_hours=24)
        runs = session.scalars(select(JobSyncRun).order_by(JobSyncRun.created_at.asc())).all()

        assert first.status == "completed"
        assert second.status == "skipped_fresh"
        assert len(runs) == 2
        assert runs[0].status == "completed"
        assert runs[1].status == "skipped_fresh"
        assert runs[1].raw_result_count == 0
        assert runs[1].normalized_count == 0
        assert runs[1].criteria_json["apiPath"] == "/jobs/search"
        assert runs[1].criteria_json["what"] == "Applied AI Engineer"
        assert runs[1].criteria_json["skipReason"] == "fresh"
        assert runs[1].criteria_json["freshnessHours"] == 24
        assert runs[1].criteria_json["latestCompletedAt"]
        assert is_sync_fresh(session, request.sync_key) is True

        skipped_only_key = "test-provider:broad:skipped-only"
        record_job_sync_run(
            session,
            JobSyncResult(
                request=JobSyncRequest(
                    sync_key=skipped_only_key,
                    provider_name="test_provider",
                    provider_type="broad_search",
                    sync_kind="broad_search",
                ),
                status="skipped_fresh",
            ),
        )
        assert is_sync_fresh(session, skipped_only_key) is False


def test_known_location_resolves_from_stored_mapping() -> None:
    engine = create_engine_for_job_sync_tests()
    with Session(engine) as session:
        mapping = resolve_provider_location_mapping(
            session,
            provider_name="adzuna",
            display_location="Remote UK",
            default_provider_country="us",
        )

        assert mapping.provider_country == "gb"
        assert mapping.provider_where is None
        assert mapping.confidence == "high"
        assert mapping.verification_status == "verified"
        assert mapping.job_location_target.normalized_key == "remote-uk"
        assert len(session.scalars(select(JobLocationTarget)).all()) == 5


def test_unknown_location_creates_low_confidence_needs_review_mapping() -> None:
    engine = create_engine_for_job_sync_tests()
    with Session(engine) as session:
        mapping = resolve_provider_location_mapping(
            session,
            provider_name="adzuna",
            display_location="Atlantis",
            default_provider_country="gb",
        )

        assert mapping.provider_country == "gb"
        assert mapping.provider_where == "Atlantis"
        assert mapping.confidence == "low"
        assert mapping.verification_status == "needs_review"
        assert mapping.diagnostics_json["providerCountrySource"] == "default_provider_country"
        assert mapping.job_location_target.normalized_key == "atlantis"
        assert mapping.job_location_target.country_code is None
        assert mapping.job_location_target.verification_status == "needs_review"


def test_adzuna_sync_plan_uses_resolved_location_mapping() -> None:
    engine = create_engine_for_job_sync_tests()
    provider = AdzunaJobSyncProvider()
    with Session(engine) as session:
        plan = provider.build_sync_plan(
            provider_country="us",
            locations=["Remote UK", "Manchester, UK", "Louisville, KY"],
            queries=["Applied AI Engineer"],
            db_session=session,
        )
        remote_uk, manchester, louisville = plan.requests

        assert remote_uk.sync_key == "adzuna:broad:gb:remote-uk:applied-ai-engineer"
        assert remote_uk.provider_country == "gb"
        assert remote_uk.provider_where is None
        assert remote_uk.criteria_json["apiPath"] == "/v1/api/jobs/gb/search/1"
        assert remote_uk.criteria_json["normalizedLocationKey"] == "remote-uk"

        assert manchester.sync_key == "adzuna:broad:gb:manchester-uk:applied-ai-engineer"
        assert manchester.provider_country == "gb"
        assert manchester.provider_where == "Manchester"
        assert manchester.display_location == "Manchester, UK"
        assert manchester.criteria_json["providerCountry"] == "gb"
        assert manchester.criteria_json["apiPath"] == "/v1/api/jobs/gb/search/1"
        assert manchester.criteria_json["where"] == "Manchester"
        assert manchester.criteria_json["normalizedLocationKey"] == "manchester-uk"
        assert manchester.criteria_json["locationConfidence"] == "high"
        assert manchester.criteria_json["locationVerificationStatus"] == "verified"

        assert louisville.sync_key == "adzuna:broad:us:louisville-ky:applied-ai-engineer"
        assert louisville.provider_country == "us"
        assert louisville.provider_where == "Louisville, Kentucky"
        assert louisville.criteria_json["apiPath"] == "/v1/api/jobs/us/search/1"
        assert louisville.criteria_json["normalizedLocationKey"] == "louisville-ky"


def test_low_confidence_location_mapping_appears_in_adzuna_request_criteria() -> None:
    engine = create_engine_for_job_sync_tests()
    provider = AdzunaJobSyncProvider()
    with Session(engine) as session:
        request = provider.build_sync_plan(
            provider_country="gb",
            locations=["Atlantis"],
            queries=["Applied AI Engineer"],
            db_session=session,
        ).requests[0]

        assert request.sync_key == "adzuna:broad:gb:atlantis:applied-ai-engineer"
        assert request.provider_country == "gb"
        assert request.criteria_json["apiPath"] == "/v1/api/jobs/gb/search/1"
        assert request.criteria_json["normalizedLocationKey"] == "atlantis"
        assert request.criteria_json["where"] == "Atlantis"
        assert request.criteria_json["locationConfidence"] == "low"
        assert request.criteria_json["locationVerificationStatus"] == "needs_review"
        assert request.criteria_json["providerLocationMappingId"]


def test_adzuna_unknown_location_without_country_does_not_default_to_us() -> None:
    engine = create_engine_for_job_sync_tests()
    provider = AdzunaJobSyncProvider()
    with Session(engine) as session:
        with pytest.raises(ValueError, match="provider country could not be resolved"):
            provider.build_sync_plan(
                provider_country=None,
                locations=["Atlantis"],
                queries=["Applied AI Engineer"],
                db_session=session,
            )
        mapping = session.scalar(
            select(JobProviderLocationMapping)
            .join(JobLocationTarget, JobLocationTarget.id == JobProviderLocationMapping.job_location_target_id)
            .where(JobLocationTarget.normalized_key == "atlantis")
        )

        assert mapping is not None
        assert mapping.provider_country is None
        assert mapping.provider_where == "Atlantis"
        assert mapping.verification_status == "needs_review"
        assert mapping.diagnostics_json["needsReviewReason"] == "No verified provider location mapping existed."


def test_location_mapping_maintenance_update_marks_mapping_verified(monkeypatch) -> None:
    engine = create_engine_for_job_sync_tests()
    with Session(engine) as session:
        mapping = resolve_provider_location_mapping(
            session,
            provider_name="adzuna",
            display_location="Atlantis",
            default_provider_country="gb",
        )
        mapping_id = mapping.id
        session.commit()

    monkeypatch.setattr(cli_module, "create_db_engine", lambda: engine)
    cli_module.update_job_location_mapping_command(
        mapping_id=mapping_id,
        provider_country="us",
        provider_where="Atlantis, Georgia",
        confidence="high",
        verification_status="verified",
    )

    with Session(engine) as session:
        updated = session.get(JobProviderLocationMapping, mapping_id)
        assert updated is not None
        assert updated.provider_country == "us"
        assert updated.provider_where == "Atlantis, Georgia"
        assert updated.confidence == "high"
        assert updated.verification_status == "verified"


def test_sync_key_construction_and_location_normalization() -> None:
    assert build_greenhouse_sync_key("Anthropic/") == "greenhouse:board:anthropic"
    assert build_adzuna_sync_key("GB", "London", "Applied AI Engineer") == "adzuna:broad:gb:london:applied-ai-engineer"
    assert normalize_location_key("Manchester, UK") == "manchester-uk"
    assert not hasattr(job_sync_models, "normalize_job_sync_location")
    assert not hasattr(job_sync_models, "normalize_provider_country")
    assert not hasattr(job_sync_module, "normalize_job_sync_location")


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


def job_sync_settings(
    *,
    greenhouse_board_tokens: tuple[str, ...] = (),
    greenhouse_company_boards: dict[str, str] | None = None,
) -> Settings:
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
        greenhouse_board_tokens=greenhouse_board_tokens,
        greenhouse_company_boards=greenhouse_company_boards,
    )


def install_greenhouse_fetch_mock(
    monkeypatch,
    *,
    board_token: str,
    jobs: list[dict[str, object]],
) -> list[tuple[str, dict[str, object] | None]]:
    requested: list[tuple[str, dict[str, object] | None]] = []

    def fake_fetch_json(url: str, *, params: dict[str, object] | None = None):
        requested.append((url, params))
        if url == f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs":
            return {"jobs": jobs, "meta": {"total": len(jobs)}}
        prefix = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/"
        if url.startswith(prefix):
            job_id = int(url.removeprefix(prefix))
            list_job = next((job for job in jobs if str(job.get("id")) == str(job_id)), None)
            if list_job is None:
                raise AssertionError(f"Unexpected Greenhouse detail URL: {url}")
            return greenhouse_retrieve_job_raw(
                job_id=job_id,
                title=str(list_job.get("title") or "Product Engineer"),
                board_token=board_token,
            )
        raise AssertionError(f"Unexpected Greenhouse URL: {url}")

    monkeypatch.setattr("jobops_api.job_discovery.job_sync.providers.greenhouse.client.fetch_json", fake_fetch_json)
    return requested


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


def greenhouse_list_job_raw(*, job_id: int = 44444, title: str = "Product Engineer", board_token: str = "vaulttec") -> dict[str, object]:
    return {
        "id": job_id,
        "internal_job_id": job_id + 11111,
        "title": title,
        "updated_at": "2013-07-02T19:39:23Z",
        "requisition_id": "50",
        "location": {"name": "San Francisco, CA"},
        "absolute_url": f"https://boards.greenhouse.io/{board_token}/jobs/{job_id}",
        "language": "en",
        "metadata": None,
        "content": "This is the job description.",
        "departments": [
            {
                "id": 13583,
                "name": "Department of Departments",
                "parent_id": None,
                "child_ids": [13585],
            }
        ],
        "offices": [
            {
                "id": 8304,
                "name": "East Coast",
                "location": "United States",
                "parent_id": None,
                "child_ids": [8787],
            }
        ],
    }


def greenhouse_retrieve_job_raw(*, job_id: int = 44444, title: str = "Product Engineer", board_token: str = "vaulttec") -> dict[str, object]:
    return {
        "id": job_id,
        "title": title,
        "updated_at": "2013-07-02T19:39:23Z",
        "requisition_id": "50",
        "location": {"name": "San Francisco, CA"},
        "content": "This is the job description.",
        "absolute_url": f"https://boards.greenhouse.io/{board_token}/jobs/{job_id}",
        "language": "en",
        "internal_job_id": job_id + 11111,
        "location_questions": [
            {
                "label": "Location",
                "fields": [{"name": "location", "type": "input_text", "values": []}],
                "required": True,
            }
        ],
        "questions": [
            {
                "required": True,
                "label": "First Name",
                "fields": [{"name": "first_name", "type": "input_text"}],
            },
            {
                "required": True,
                "label": "Resume",
                "fields": [
                    {"name": "resume", "type": "input_file"},
                    {"name": "resume_text", "type": "textarea"},
                ],
            },
        ],
        "metadata": [{"id": 12345, "name": "Field Name", "value_type": "text", "value": "Some value"}],
        "compliance": [
            {
                "required": False,
                "label": "Veteran Status",
                "fields": [{"name": "eeoc_veteran_status", "type": "multi_value_single_select", "values": []}],
            }
        ],
        "data_compliance": [
            {
                "type": "gdpr",
                "requires_consent": True,
                "requires_processing_consent": True,
                "requires_retention_consent": True,
                "retention_period": 12345,
            }
        ],
        "demographic_questions": {
            "header": "Diversity and Inclusion at Acme Corp.",
            "description": "<p>Acme Corp. is dedicated to...</p>",
            "questions": [
                {
                    "id": 1,
                    "label": "Favorite Color",
                    "required": False,
                    "type": "multi_value_multi_select",
                    "answer_options": [{"id": 100, "label": "Red", "free_form": False}],
                }
            ],
        },
        "pay_input_ranges": [
            {
                "min_cents": 5000000,
                "max_cents": 7500000,
                "currency_type": "USD",
                "title": "NYC Salary Range",
                "blurb": "In order to provide transparency...",
            }
        ],
    }


def greenhouse_retrieve_request(board_token: str, job_id: str) -> dict[str, object]:
    return {
        "url": f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{job_id}",
        "params": {"questions": "true", "pay_transparency": "true"},
    }


def adzuna_source(*, provider_job_id: str, source_url: str | None = None) -> JobListingSourceRecord:
    resolved_url = source_url or f"https://adzuna.example.test/jobs/{provider_job_id}"
    return JobListingSourceRecord(
        source_provider="adzuna",
        provider_type="broad_search",
        provider_job_id=provider_job_id,
        source_result_id=provider_job_id,
        source_url=resolved_url,
        apply_url=resolved_url,
        canonical_url=resolved_url,
        source_query="Applied AI Engineer",
        source_country="us",
        raw_metadata_json={"id": provider_job_id},
        source_status="active",
    )


def generic_source(*, provider_job_id: str | None, source_url: str) -> JobListingSourceRecord:
    return JobListingSourceRecord(
        source_provider="provider_without_ids",
        provider_type="broad_search",
        provider_job_id=provider_job_id,
        source_result_id=provider_job_id,
        source_url=source_url,
        apply_url=source_url,
        canonical_url=source_url,
        source_query="Applied AI Engineer",
        source_country="us",
        raw_metadata_json={},
        source_status="active",
    )


def adzuna_sync_request() -> JobSyncRequest:
    return JobSyncRequest(
        sync_key=build_adzuna_sync_key("us", "remote-us", "Applied AI Engineer"),
        provider_name="adzuna",
        provider_type="broad_search",
        sync_kind="broad_search",
        provider_country="us",
        display_location="Remote US",
        query_text="Applied AI Engineer",
        criteria_json={
            "providerCountry": "us",
            "apiPath": "/v1/api/jobs/us/search/1",
            "page": 1,
            "what": "Applied AI Engineer",
            "where": None,
            "resultsPerPage": 50,
            "contentType": "application/json",
            "syncKey": build_adzuna_sync_key("us", "remote-us", "Applied AI Engineer"),
        },
    )


def adzuna_raw(
    *,
    id: object,
    title: str = "Applied AI Engineer",
    redirect_url: str = "https://adzuna.example.test/redirect?job=1&tracking=one",
) -> dict[str, object]:
    return {
        "id": id,
        "title": title,
        "company": {"display_name": "Acme AI"},
        "redirect_url": redirect_url,
        "description": "Applied AI role",
        "location": {"display_name": "Remote US"},
        "created": "2026-06-01T12:00:00Z",
    }
