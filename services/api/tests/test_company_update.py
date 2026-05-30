from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from jobops_api.company_canonicalization import ensure_candidate_company_link, upsert_canonical_company
from jobops_api.company_update import CompanyUpdateRequest, run_company_update
from jobops_api.db.models import Base, CandidateCompany, Company
from jobops_api.db.seed_profile import seed_public_profile
from jobops_api.profiles import get_candidate_profile_by_slug


def test_company_url_updates_persist_to_db() -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        company = add_company(session, profile.id, "CivicActions")
        link_id = company.id

        result = run_company_update(
            CompanyUpdateRequest(
                company_id=company.id,
                company_name=None,
                field="website_url",
                url="https://civicactions.com",
            ),
            candidate_profile=profile,
            db_session=session,
        )

    with Session(engine) as session:
        saved = session.get(CandidateCompany, link_id)
        assert result.status == "completed"
        assert saved is not None
        assert saved.company.website_url == "https://civicactions.com"
        assert saved.derivation_status == "model_derived"
        assert saved.review_status == "new"


def test_careers_and_job_listings_updates_persist_to_db() -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        company = add_company(session, profile.id, "CivicActions")
        link_id = company.id

        careers = run_company_update(
            CompanyUpdateRequest(
                company_id=None,
                company_name="CivicActions",
                field="careers_url",
                url="https://civicactions.com/careers",
            ),
            candidate_profile=profile,
            db_session=session,
        )
        listings = run_company_update(
            CompanyUpdateRequest(
                company_id=None,
                company_name="CivicActions",
                field="job_listings_url",
                url="https://civicactions.com/jobs",
            ),
            candidate_profile=profile,
            db_session=session,
        )

    with Session(engine) as session:
        saved = session.get(CandidateCompany, link_id)
        assert careers.status == "completed"
        assert listings.status == "completed"
        assert saved is not None
        assert saved.company.careers_url == "https://civicactions.com/careers"
        assert saved.company.job_listings_url == "https://civicactions.com/jobs"


def test_source_url_appends_without_duplicates() -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        company = add_company(session, profile.id, "CivicActions", source_urls=["https://civicactions.com"])
        link_id = company.id

        first = run_company_update(
            CompanyUpdateRequest(
                company_id=None,
                company_name="CivicActions",
                field="source_urls",
                url="https://example.com/source",
            ),
            candidate_profile=profile,
            db_session=session,
        )
        second = run_company_update(
            CompanyUpdateRequest(
                company_id=None,
                company_name="CivicActions",
                field="source_urls",
                url="https://example.com/source",
            ),
            candidate_profile=profile,
            db_session=session,
        )

    with Session(engine) as session:
        saved = session.get(CandidateCompany, link_id)
        assert first.body["result"]["appended"] is True
        assert second.body["result"]["appended"] is False
        assert saved is not None
        assert saved.company.source_urls == ["https://civicactions.com", "https://example.com/source"]


def test_unknown_company_returns_clarification_without_creating_company() -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None

        result = run_company_update(
            CompanyUpdateRequest(
                company_id=None,
                company_name="Missing Co",
                field="careers_url",
                url="https://missing.example/jobs",
            ),
            candidate_profile=profile,
            db_session=session,
        )
        count = len(list(session.scalars(select(CandidateCompany))))

    assert result.status == "needs_confirmation"
    assert result.body["code"] == "company_not_found"
    assert count == 0


def test_ambiguous_company_match_returns_clarification() -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        add_company(session, profile.id, "Example", normalized_name="example", source_urls=["https://example-one.com"])
        add_company(session, profile.id, "EXAMPLE", normalized_name="example", source_urls=["https://example-two.com"])

        result = run_company_update(
            CompanyUpdateRequest(
                company_id=None,
                company_name="example",
                field="careers_url",
                url="https://example.com/jobs",
            ),
            candidate_profile=profile,
            db_session=session,
        )

    assert result.status == "needs_confirmation"
    assert result.body["code"] == "company_update_ambiguous_target"
    assert len(result.body["matches"]) == 2


def test_unsupported_field_is_rejected() -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        add_company(session, profile.id, "CivicActions")

        result = run_company_update(
            CompanyUpdateRequest(
                company_id=None,
                company_name="CivicActions",
                field="unsupported_field",
                url="https://civicactions.com",
            ),
            candidate_profile=profile,
            db_session=session,
        )

    assert result.status == "failed"
    assert result.body["code"] == "unsupported_company_update_field"


def create_seeded_engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_public_profile(
            session,
            {
                "slug": "rebekah-love",
                "displayName": "Rebekah Love",
                "headline": "Candidate profile setup in progress",
                "summary": "Verified public profile facts are being reviewed before publication.",
                "profileStatus": "draft",
            },
            hostname="rebekahalove.dev",
        )
        session.commit()
    return engine


def add_company(
    session: Session,
    candidate_profile_id: str,
    name: str,
    *,
    normalized_name: str | None = None,
    source_urls: list[str] | None = None,
) -> CandidateCompany:
    company = upsert_canonical_company(
        session,
        name=name,
        normalized_name=normalized_name or name.casefold(),
        source_urls=source_urls or [],
    )
    link = ensure_candidate_company_link(
        session,
        candidate_profile_id=candidate_profile_id,
        company=company,
        derivation_status="model_derived",
        review_status="new",
    )
    session.commit()
    session.refresh(link.link)
    return link.link
