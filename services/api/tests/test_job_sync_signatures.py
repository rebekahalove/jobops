from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from jobops_api.db.models import Base, JobListing, JobListingSource, JobSyncRun, JobSyncSignature
from jobops_api.job_discovery.job_sync.adzuna_service import sync_adzuna_signatures, upsert_adzuna_sync_signature
from jobops_api.settings import Settings


def test_upsert_adzuna_signature_for_remote_uk_creates_stable_sync_key() -> None:
    engine = create_engine_for_signature_tests()

    with Session(engine) as session:
        signature = upsert_adzuna_sync_signature(
            session,
            query_text="AI",
            display_location="Remote UK",
            query_kind="broad_term",
            max_pages=2,
        )

        assert signature.provider_name == "adzuna"
        assert signature.provider_country == "gb"
        assert signature.normalized_location_key == "remote-uk"
        assert signature.sync_key == "adzuna:broad:gb:remote-uk:ai"
        assert signature.criteria_json["what"] == "AI"
        assert signature.criteria_json["providerCountry"] == "gb"
        assert signature.criteria_json["maxPages"] == 2
        assert signature.criteria_json["jobSyncSignatureId"] == signature.id


def test_upsert_adzuna_signature_updates_existing_query_location_row() -> None:
    engine = create_engine_for_signature_tests()

    with Session(engine) as session:
        first = upsert_adzuna_sync_signature(
            session,
            query_text="AI",
            display_location="Remote UK",
            max_pages=1,
        )
        second = upsert_adzuna_sync_signature(
            session,
            query_text="AI",
            display_location="Remote UK",
            query_kind="skill_term",
            max_pages=3,
        )

        assert first.id == second.id
        assert second.query_kind == "skill_term"
        assert second.max_pages == 3
        assert len(session.scalars(select(JobSyncSignature)).all()) == 1


def test_unknown_adzuna_signature_without_country_is_disabled_needs_review() -> None:
    engine = create_engine_for_signature_tests()

    with Session(engine) as session:
        signature = upsert_adzuna_sync_signature(
            session,
            query_text="Engineer",
            display_location="Atlantis",
        )

        assert signature.enabled is False
        assert signature.provider_country is None
        assert signature.sync_key == "adzuna:broad:unknown:atlantis:engineer"
        assert signature.verification_status == "needs_review"
        assert signature.criteria_json["providerCountry"] is None
        assert signature.criteria_json["locationVerificationStatus"] == "needs_review"


def test_unknown_adzuna_signature_with_explicit_country_records_low_confidence_review_metadata() -> None:
    engine = create_engine_for_signature_tests()

    with Session(engine) as session:
        signature = upsert_adzuna_sync_signature(
            session,
            query_text="Engineer",
            display_location="Atlantis",
            provider_country="gb",
        )

        assert signature.enabled is True
        assert signature.provider_country == "gb"
        assert signature.sync_key == "adzuna:broad:gb:atlantis:engineer"
        assert signature.verification_status == "needs_review"
        assert signature.criteria_json["locationConfidence"] == "low"
        assert signature.criteria_json["locationVerificationStatus"] == "needs_review"


def test_sync_stale_adzuna_signature_fetches_pages_upserts_jobs_and_updates_signature(monkeypatch) -> None:
    engine = create_engine_for_signature_tests()
    requested = install_adzuna_fetch_mock(
        monkeypatch,
        {
            1: {
                "count": 123,
                "mean": 80668.77,
                "results": [adzuna_raw("adz-1", title="AI Engineer")],
            },
            2: {
                "count": 123,
                "mean": 80668.77,
                "results": [adzuna_raw("adz-2", title="LLM Engineer")],
            },
        },
    )

    with Session(engine) as session:
        signature = upsert_adzuna_sync_signature(
            session,
            query_text="AI",
            display_location="Manchester, UK",
            query_kind="broad_term",
            max_pages=2,
        )
        results = sync_adzuna_signatures(
            session,
            settings=adzuna_settings(),
            signature_ids=[signature.id],
            enabled_only=False,
            force=True,
        )
        listings = session.scalars(select(JobListing).order_by(JobListing.title.asc())).all()
        sources = session.scalars(select(JobListingSource).order_by(JobListingSource.provider_job_id.asc())).all()
        run = session.scalar(select(JobSyncRun))
        refreshed = session.get(JobSyncSignature, signature.id)

        assert len(results) == 1
        result = results[0]
        assert result.status == "completed"
        assert result.raw_result_count == 2
        assert result.normalized_count == 2
        assert result.created_count == 2
        assert len(listings) == 2
        assert len(sources) == 2
        assert run is not None
        assert run.job_sync_signature_id == signature.id
        assert run.criteria_json["what"] == "AI"
        assert run.criteria_json["where"] == "Manchester"
        assert run.criteria_json["apiPath"] == "/v1/api/jobs/gb/search/1"
        assert run.criteria_json["resultsPerPage"] == 50
        assert run.criteria_json["providerReportedCount"] == 123
        assert run.criteria_json["providerReportedMean"] == 80668.77
        assert run.criteria_json["pagesFetched"] == 2
        assert run.criteria_json["pageDiagnostics"][1]["apiPath"] == "/v1/api/jobs/gb/search/2"
        assert "app_id" not in str(run.criteria_json)
        assert "app_key" not in str(run.criteria_json)
        assert refreshed is not None
        assert refreshed.last_status == "completed"
        assert refreshed.last_attempted_at is not None
        assert refreshed.last_completed_at is not None
        assert refreshed.last_raw_result_count == 2
        assert refreshed.last_normalized_count == 2
        assert refreshed.last_created_count == 2
        assert refreshed.last_updated_count == 0
        assert requested == [
            ("https://api.adzuna.com/v1/api/jobs/gb/search/1", {"what": "AI", "where": "Manchester", "results_per_page": 50}),
            ("https://api.adzuna.com/v1/api/jobs/gb/search/2", {"what": "AI", "where": "Manchester", "results_per_page": 50}),
        ]


def test_fresh_adzuna_signature_records_skipped_without_api_call(monkeypatch) -> None:
    engine = create_engine_for_signature_tests()

    def fail_fetch_json(url: str, *, params: dict[str, object] | None = None):
        raise AssertionError(f"Fresh signature should not call Adzuna API: {url}")

    monkeypatch.setattr("jobops_api.job_discovery.job_sync.providers.adzuna.client.fetch_json", fail_fetch_json)
    with Session(engine) as session:
        signature = upsert_adzuna_sync_signature(session, query_text="AI", display_location="Remote UK")
        prior_completed_at = datetime.now(UTC)
        signature.last_completed_at = prior_completed_at
        signature.last_status = "completed"
        signature.last_raw_result_count = 50
        signature.last_normalized_count = 49
        signature.last_created_count = 12
        signature.last_updated_count = 37
        signature.last_error = None
        results = sync_adzuna_signatures(
            session,
            settings=adzuna_settings(),
            signature_ids=[signature.id],
            enabled_only=False,
        )
        run = session.scalar(select(JobSyncRun))
        refreshed = session.get(JobSyncSignature, signature.id)

        assert results[0].status == "skipped_fresh"
        assert run is not None
        assert run.status == "skipped_fresh"
        assert run.job_sync_signature_id == signature.id
        assert run.raw_result_count == 0
        assert refreshed is not None
        assert refreshed.last_status == "skipped_fresh"
        assert refreshed.last_attempted_at is not None
        assert refreshed.last_completed_at == prior_completed_at
        assert refreshed.last_raw_result_count == 50
        assert refreshed.last_normalized_count == 49
        assert refreshed.last_created_count == 12
        assert refreshed.last_updated_count == 37
        assert refreshed.last_error is None


def test_disabled_adzuna_signature_skip_preserves_successful_counts() -> None:
    engine = create_engine_for_signature_tests()

    with Session(engine) as session:
        signature = upsert_adzuna_sync_signature(session, query_text="AI", display_location="Remote UK")
        prior_completed_at = datetime.now(UTC)
        signature.enabled = False
        signature.last_completed_at = prior_completed_at
        signature.last_status = "completed"
        signature.last_raw_result_count = 50
        signature.last_normalized_count = 49
        signature.last_created_count = 12
        signature.last_updated_count = 37
        results = sync_adzuna_signatures(
            session,
            settings=adzuna_settings(),
            signature_ids=[signature.id],
            enabled_only=False,
        )
        run = session.scalar(select(JobSyncRun))
        refreshed = session.get(JobSyncSignature, signature.id)

        assert results[0].status == "skipped"
        assert run is not None
        assert run.status == "skipped"
        assert run.raw_result_count == 0
        assert refreshed is not None
        assert refreshed.last_status == "skipped"
        assert refreshed.last_attempted_at is not None
        assert refreshed.last_completed_at == prior_completed_at
        assert refreshed.last_raw_result_count == 50
        assert refreshed.last_normalized_count == 49
        assert refreshed.last_created_count == 12
        assert refreshed.last_updated_count == 37
        assert refreshed.last_error is None


def test_force_refresh_calls_adzuna_even_when_signature_is_fresh(monkeypatch) -> None:
    engine = create_engine_for_signature_tests()
    requested = install_adzuna_fetch_mock(monkeypatch, {1: {"count": 1, "results": [adzuna_raw("adz-1")]}})

    with Session(engine) as session:
        signature = upsert_adzuna_sync_signature(session, query_text="AI", display_location="Remote UK")
        signature.last_completed_at = datetime.now(UTC)
        results = sync_adzuna_signatures(
            session,
            settings=adzuna_settings(),
            signature_ids=[signature.id],
            enabled_only=False,
            force=True,
        )

        assert results[0].status == "completed"
        assert len(requested) == 1


def test_failed_adzuna_signature_does_not_abort_later_signature(monkeypatch) -> None:
    engine = create_engine_for_signature_tests()

    def fake_fetch_json(url: str, *, params: dict[str, object] | None = None):
        if params and params.get("what") == "Broken":
            raise RuntimeError("provider unavailable")
        return {"count": 1, "results": [adzuna_raw("adz-ok", title="AI Engineer")]}

    monkeypatch.setattr("jobops_api.job_discovery.job_sync.providers.adzuna.client.fetch_json", fake_fetch_json)
    with Session(engine) as session:
        broken = upsert_adzuna_sync_signature(session, query_text="Broken", display_location="Remote UK")
        ok = upsert_adzuna_sync_signature(session, query_text="AI", display_location="Remote UK")
        results = sync_adzuna_signatures(
            session,
            settings=adzuna_settings(),
            signature_ids=[broken.id, ok.id],
            enabled_only=False,
            force=True,
        )
        runs = session.scalars(select(JobSyncRun).order_by(JobSyncRun.created_at.asc())).all()
        listings = session.scalars(select(JobListing)).all()

        assert [result.status for result in results] == ["failed", "completed"]
        assert [run.status for run in runs] == ["failed", "completed"]
        assert len(listings) == 1


def test_failed_adzuna_signature_preserves_successful_counts(monkeypatch) -> None:
    engine = create_engine_for_signature_tests()

    def fake_fetch_json(url: str, *, params: dict[str, object] | None = None):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("jobops_api.job_discovery.job_sync.providers.adzuna.client.fetch_json", fake_fetch_json)
    with Session(engine) as session:
        signature = upsert_adzuna_sync_signature(session, query_text="AI", display_location="Remote UK")
        prior_completed_at = datetime.now(UTC)
        signature.last_completed_at = prior_completed_at
        signature.last_status = "completed"
        signature.last_raw_result_count = 50
        signature.last_normalized_count = 49
        signature.last_created_count = 12
        signature.last_updated_count = 37
        results = sync_adzuna_signatures(
            session,
            settings=adzuna_settings(),
            signature_ids=[signature.id],
            enabled_only=False,
            force=True,
        )
        run = session.scalar(select(JobSyncRun))
        refreshed = session.get(JobSyncSignature, signature.id)

        assert results[0].status == "failed"
        assert run is not None
        assert run.status == "failed"
        assert run.raw_result_count == 0
        assert refreshed is not None
        assert refreshed.last_status == "failed"
        assert refreshed.last_error == "provider unavailable"
        assert refreshed.last_attempted_at is not None
        assert refreshed.last_completed_at == prior_completed_at
        assert refreshed.last_raw_result_count == 50
        assert refreshed.last_normalized_count == 49
        assert refreshed.last_created_count == 12
        assert refreshed.last_updated_count == 37


def test_missing_adzuna_id_fails_normalization_during_signature_sync(monkeypatch) -> None:
    engine = create_engine_for_signature_tests()
    raw = adzuna_raw("adz-missing")
    raw.pop("id")
    install_adzuna_fetch_mock(monkeypatch, {1: {"count": 1, "results": [raw]}})

    with Session(engine) as session:
        signature = upsert_adzuna_sync_signature(session, query_text="AI", display_location="Remote UK")
        result = sync_adzuna_signatures(
            session,
            settings=adzuna_settings(),
            signature_ids=[signature.id],
            enabled_only=False,
            force=True,
        )[0]

        assert result.raw_result_count == 1
        assert result.normalized_count == 0
        assert result.failed_normalization_count == 1
        assert session.scalars(select(JobListing)).all() == []


def test_same_adzuna_id_updates_existing_source_from_signature_sync(monkeypatch) -> None:
    engine = create_engine_for_signature_tests()
    install_adzuna_fetch_mock(monkeypatch, {1: {"count": 1, "results": [adzuna_raw("adz-1", title="First Title")]}})

    with Session(engine) as session:
        signature = upsert_adzuna_sync_signature(session, query_text="AI", display_location="Remote UK")
        first = sync_adzuna_signatures(
            session,
            settings=adzuna_settings(),
            signature_ids=[signature.id],
            enabled_only=False,
            force=True,
        )[0]
        install_adzuna_fetch_mock(monkeypatch, {1: {"count": 1, "results": [adzuna_raw("adz-1", title="Updated Title")]}})
        second = sync_adzuna_signatures(
            session,
            settings=adzuna_settings(),
            signature_ids=[signature.id],
            enabled_only=False,
            force=True,
        )[0]
        listing = session.scalar(select(JobListing))

        assert first.created_count == 1
        assert second.updated_count == 1
        assert listing is not None
        assert listing.title == "Updated Title"
        assert len(session.scalars(select(JobListing)).all()) == 1


def create_engine_for_signature_tests():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def adzuna_settings() -> Settings:
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
        adzuna_app_id="app-id",
        adzuna_app_key="app-key",
    )


def install_adzuna_fetch_mock(monkeypatch, responses_by_page: dict[int, dict[str, object]]) -> list[tuple[str, dict[str, object]]]:
    requested: list[tuple[str, dict[str, object]]] = []

    def fake_fetch_json(url: str, *, params: dict[str, object] | None = None):
        assert params is not None
        requested.append(
            (
                url,
                {
                    "what": params.get("what"),
                    "where": params.get("where"),
                    "results_per_page": params.get("results_per_page"),
                },
            )
        )
        page = int(url.rsplit("/", 1)[-1])
        return responses_by_page[page]

    monkeypatch.setattr("jobops_api.job_discovery.job_sync.providers.adzuna.client.fetch_json", fake_fetch_json)
    return requested


def adzuna_raw(provider_job_id: str, *, title: str = "Applied AI Engineer") -> dict[str, object]:
    return {
        "id": provider_job_id,
        "title": title,
        "company": {"display_name": "Acme AI"},
        "redirect_url": f"https://adzuna.example.test/redirect?job={provider_job_id}&tracking=one",
        "description": "Applied AI role",
        "location": {
            "display_name": "Manchester, Greater Manchester",
            "area": ["GB", "North West England", "Greater Manchester", "Manchester"],
        },
        "created": "2026-06-01T12:00:00Z",
    }
