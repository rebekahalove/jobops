from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
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

    alembic_config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(alembic_config, "head")

    engine = create_engine(database_url)
    inspector = inspect_database(engine)

    assert "profile_intake_events" in inspector.get_table_names()
    assert "experience_project_drafts" in inspector.get_table_names()
    assert "last_turn_at" in {column["name"] for column in inspector.get_columns("profile_intake_sessions")}
    experience_columns = {column["name"] for column in inspector.get_columns("experience_project_drafts")}
    assert {"start_date", "end_date", "location"}.issubset(experience_columns)
    company_columns = {column["name"] for column in inspector.get_columns("target_companies")}
    assert {
        "normalized_name",
        "careers_url",
        "job_listings_url",
        "derivation_status",
        "review_status",
        "provider_grounding_metadata",
    }.issubset(company_columns)
