from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy import inspect as inspect_database
from sqlalchemy.orm import Session

from jobops_api.db.models import Base, CandidateProfile, Domain, Tenant
from jobops_api.db.seed_profile import seed_public_profile
from jobops_api.db.session import database_url_for_sqlalchemy


def test_database_url_for_sqlalchemy_prefers_psycopg_driver() -> None:
    assert database_url_for_sqlalchemy("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert database_url_for_sqlalchemy("postgresql://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert database_url_for_sqlalchemy("postgresql+psycopg://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert database_url_for_sqlalchemy("sqlite+pysqlite:///:memory:") == "sqlite+pysqlite:///:memory:"


def test_seed_public_profile_is_idempotent_with_sqlite() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    profile = {
        "slug": "rebekah-love",
        "displayName": "Rebekah Love",
        "headline": "Candidate profile setup in progress",
        "summary": "Verified public profile facts are being reviewed before publication.",
        "profileStatus": "draft",
    }

    with Session(engine) as session:
        first = seed_public_profile(session, profile, hostname="rebekahalove.dev")
        session.commit()
        second = seed_public_profile(session, profile, hostname="rebekahalove.dev")
        session.commit()

        assert first.id == second.id
        assert session.scalars(select(Tenant)).all()[0].slug == "rebekah-love"
        assert len(session.scalars(select(CandidateProfile)).all()) == 1
        assert session.scalars(select(Domain)).all()[0].hostname == "rebekahalove.dev"


def test_alembic_migrations_apply_to_sqlite(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "jobops_migration_test.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", database_url)

    api_root = Path(__file__).resolve().parents[1]
    alembic_config = Config(str(api_root / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(api_root / "alembic"))
    command.upgrade(alembic_config, "head")

    engine = create_engine(database_url)
    inspector = inspect_database(engine)

    assert "profile_intake_events" in inspector.get_table_names()
    assert "experience_project_drafts" in inspector.get_table_names()
    assert "profile_field_values" in inspector.get_table_names()
    assert "last_turn_at" in {column["name"] for column in inspector.get_columns("profile_intake_sessions")}
    field_value_columns = {column["name"] for column in inspector.get_columns("profile_field_values")}
    assert {
        "id",
        "candidate_profile_id",
        "field_group",
        "field_name",
        "value_text",
        "source",
        "lifecycle_status",
        "visibility",
        "original_value_text",
        "archive_reason",
        "metadata",
        "published_at",
        "archived_at",
        "created_at",
        "updated_at",
    }.issubset(field_value_columns)
    experience_columns = {column["name"] for column in inspector.get_columns("experience_project_drafts")}
    assert {"start_date", "end_date", "location"}.issubset(experience_columns)
    assert "target_companies" not in inspector.get_table_names()
    canonical_company_columns = {column["name"] for column in inspector.get_columns("companies")}
    assert {
        "normalized_name",
        "normalized_domain",
        "website_url",
        "careers_url",
        "job_listings_url",
        "greenhouse_board_token",
        "first_seen_at",
        "last_seen_at",
    }.issubset(canonical_company_columns)
    candidate_company_columns = {column["name"] for column in inspector.get_columns("candidate_companies")}
    assert {
        "candidate_profile_id",
        "company_id",
        "fit_reason",
        "role_fit_tags",
        "mission_fit_tags",
        "notes",
        "added_at",
    }.issubset(candidate_company_columns)
    job_role_columns = {column["name"] for column in inspector.get_columns("job_roles")}
    application_columns = {column["name"] for column in inspector.get_columns("applications")}
    assert "company_id" in job_role_columns
    assert "target_company_id" not in job_role_columns
    assert "company_id" in application_columns
    assert "job_id" in application_columns
    assert "saved_job_id" in application_columns
    assert "target_company_id" not in application_columns
    assert "job_listings" in inspector.get_table_names()
    assert "job_listing_sources" in inspector.get_table_names()
    assert "job_sync_runs" in inspector.get_table_names()
    assert "job_location_targets" in inspector.get_table_names()
    assert "job_provider_location_mappings" in inspector.get_table_names()
    job_listing_columns = {column["name"] for column in inspector.get_columns("job_listings")}
    assert {
        "title",
        "job_location_target_id",
        "company_id",
        "company_name",
        "canonical_url",
        "apply_url",
        "source_url",
        "location_raw",
        "location_display",
        "location_country",
        "remote_work_mode",
        "salary_min",
        "salary_max",
        "source_updated_at",
        "last_synced_at",
        "is_active",
        "source_status",
    }.issubset(job_listing_columns)
    job_listing_source_columns = {column["name"] for column in inspector.get_columns("job_listing_sources")}
    assert {
        "job_listing_id",
        "source_provider",
        "provider_type",
        "provider_job_id",
        "ats_provider",
        "ats_board_token",
        "source_query",
        "raw_metadata_json",
        "last_synced_at",
        "is_active",
    }.issubset(job_listing_source_columns)
    job_sync_run_columns = {column["name"] for column in inspector.get_columns("job_sync_runs")}
    assert {
        "sync_key",
        "provider_name",
        "provider_type",
        "sync_kind",
        "provider_country",
        "provider_where",
        "query_text",
        "criteria_json",
        "completed_at",
        "created_count",
        "updated_count",
    }.issubset(job_sync_run_columns)
    job_location_target_columns = {column["name"] for column in inspector.get_columns("job_location_targets")}
    assert {
        "display_name",
        "normalized_key",
        "location_kind",
        "city",
        "region",
        "country_code",
        "confidence",
        "verification_status",
        "raw_inputs_json",
    }.issubset(job_location_target_columns)
    provider_location_mapping_columns = {column["name"] for column in inspector.get_columns("job_provider_location_mappings")}
    assert {
        "job_location_target_id",
        "provider_name",
        "provider_country",
        "provider_where",
        "display_location",
        "confidence",
        "verification_status",
        "diagnostics_json",
    }.issubset(provider_location_mapping_columns)


def test_job_listing_title_downgrade_preserves_long_provider_titles(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "jobops_long_title_downgrade_test.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", database_url)

    api_root = Path(__file__).resolve().parents[1]
    alembic_config = Config(str(api_root / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(api_root / "alembic"))
    command.upgrade(alembic_config, "20260612_0032")

    long_title = (
        "Senior AI & Data Analytics Architect - Atlanta GA, Hybrid(3 days Onsite). In-person is mandatory and "
        "preferred only locals. Must have strong experience in Python, SQL, Machine Learning, Deep Learning, NLP, "
        "Generative AI, GPT, Claude, Gemini, Llama, Mistral, governance, monitoring, and analytics platforms"
    )
    assert len(long_title) > 240
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO job_listings (id, title, company_name, is_active) "
                "VALUES ('listing-1', :title, 'Long Title Co', 1)"
            ),
            {"title": long_title},
        )

    command.downgrade(alembic_config, "20260611_0031")

    with engine.connect() as connection:
        stored_title = connection.scalar(text("SELECT title FROM job_listings WHERE id = 'listing-1'"))

    assert stored_title == long_title


def test_candidate_saved_jobs_downgrade_preserves_synced_saved_rows(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "jobops_synced_saved_job_downgrade_test.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", database_url)

    api_root = Path(__file__).resolve().parents[1]
    alembic_config = Config(str(api_root / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(api_root / "alembic"))
    command.upgrade(alembic_config, "20260611_0031")

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO tenants (id, name, slug) VALUES ('tenant-1', 'Tenant', 'tenant')"))
        connection.execute(
            text(
                "INSERT INTO candidate_profiles (id, tenant_id, slug, display_name, headline, summary, profile_status) "
                "VALUES ('profile-1', 'tenant-1', 'one', 'One', 'Headline', '', 'draft')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO job_listings (id, title, company_name, is_active) "
                "VALUES ('listing-1', 'Synced Job', 'Synced Co', 1)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO candidate_saved_jobs (id, candidate_profile_id, job_id, job_listing_id, status) "
                "VALUES ('saved-1', 'profile-1', NULL, 'listing-1', 'new')"
            )
        )

    command.downgrade(alembic_config, "20260610_0030")
    command.upgrade(alembic_config, "head")

    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT job_id, job_listing_id, status FROM candidate_saved_jobs WHERE id = 'saved-1'")
        ).mappings().one()

    assert row["job_id"] is None
    assert row["job_listing_id"] == "listing-1"
    assert row["status"] == "new"


def test_canonical_company_migration_backfills_target_companies(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "jobops_company_backfill_test.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", database_url)

    api_root = Path(__file__).resolve().parents[1]
    alembic_config = Config(str(api_root / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(api_root / "alembic"))
    command.upgrade(alembic_config, "20260528_0016")

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO tenants (id, name, slug) VALUES ('tenant-1', 'Tenant', 'tenant')"))
        connection.execute(
            text(
                "INSERT INTO candidate_profiles (id, tenant_id, slug, display_name, headline, summary, profile_status) "
                "VALUES ('profile-1', 'tenant-1', 'one', 'One', 'Headline', '', 'draft'), "
                "('profile-2', 'tenant-1', 'two', 'Two', 'Headline', '', 'draft')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO target_companies "
                "(id, candidate_profile_id, name, normalized_name, website_url, source_urls, role_fit_tags, mission_fit_tags, fit_reason, review_status, derivation_status, notes) "
                "VALUES "
                "('target-1', 'profile-1', 'Civic Co', 'civic co', 'https://civic.example', '[\"https://civic.example\"]', '[\"AI\"]', '[\"Civic tech\"]', 'Good fit', 'new', 'model_derived', 'Private note'), "
                "('target-2', 'profile-2', 'Civic Co', 'civic co', 'https://civic.example/about', '[\"https://civic.example/about\"]', '[\"Backend\"]', '[\"Public interest\"]', 'Other fit', 'reviewed', 'user_entered', 'Second note')"
            )
        )

    command.upgrade(alembic_config, "head")

    with engine.connect() as connection:
        companies_count = connection.scalar(text("SELECT COUNT(*) FROM companies"))
        links_count = connection.scalar(text("SELECT COUNT(*) FROM candidate_companies"))
        notes = list(connection.execute(text("SELECT notes FROM candidate_companies ORDER BY candidate_profile_id")).scalars())

    assert companies_count == 1
    assert links_count == 2
    assert notes == ["Private note", "Second note"]

    command.downgrade(alembic_config, "20260528_0016")
    inspector = inspect_database(engine)
    assert "target_companies" in inspector.get_table_names()
    assert "companies" not in inspector.get_table_names()
    assert "candidate_companies" not in inspector.get_table_names()


def test_application_job_link_migration_preserves_existing_applications(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "jobops_application_link_test.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", database_url)

    api_root = Path(__file__).resolve().parents[1]
    alembic_config = Config(str(api_root / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(api_root / "alembic"))
    command.upgrade(alembic_config, "20260529_0019")

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO tenants (id, name, slug) VALUES ('tenant-1', 'Tenant', 'tenant')"))
        connection.execute(
            text(
                "INSERT INTO candidate_profiles (id, tenant_id, slug, display_name, headline, summary, profile_status) "
                "VALUES ('profile-1', 'tenant-1', 'one', 'One', 'Headline', '', 'draft')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO applications "
                "(id, candidate_profile_id, company_name, job_title, job_url, location, source, date_applied, status, notes) "
                "VALUES "
                "('application-1', 'profile-1', 'Acme AI', 'Applied AI Engineer', 'https://example.test/job', "
                "'Remote', 'manual', '2026-05-13', 'applied', 'Existing note')"
            )
        )

    command.upgrade(alembic_config, "head")

    inspector = inspect_database(engine)
    application_columns = {column["name"] for column in inspector.get_columns("applications")}
    assert {"job_id", "saved_job_id"}.issubset(application_columns)
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT company_name, job_title, job_id, saved_job_id, notes FROM applications WHERE id = 'application-1'")
        ).mappings().one()

    assert row["company_name"] == "Acme AI"
    assert row["job_title"] == "Applied AI Engineer"
    assert row["job_id"] is None
    assert row["saved_job_id"] is None
    assert row["notes"] == "Existing note"
