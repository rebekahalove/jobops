from __future__ import annotations

from sqlalchemy import create_engine, select
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
