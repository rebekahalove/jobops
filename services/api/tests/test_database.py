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
