from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from jobops_api.db.models import Base, ProfileFact
from jobops_api.db.seed_profile import seed_public_profile
from jobops_api.profiles import (
    candidate_profile_to_public_dict,
    get_candidate_profile_by_hostname,
    get_candidate_profile_by_slug,
)


def test_profile_lookup_by_slug_and_hostname() -> None:
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
        seeded_profile = seed_public_profile(session, profile, hostname="rebekahalove.dev")
        session.add(
            ProfileFact(
                candidate_profile_id=seeded_profile.id,
                fact_type="skill",
                claim="Public verified fact",
                source="test",
                visibility="public",
                verification_status="published",
            )
        )
        session.add(
            ProfileFact(
                candidate_profile_id=seeded_profile.id,
                fact_type="private_note",
                claim="Private draft fact",
                source="test",
                visibility="private",
                verification_status="draft",
            )
        )
        session.commit()

        by_slug = get_candidate_profile_by_slug(session, "rebekah-love")
        by_hostname = get_candidate_profile_by_hostname(session, "REBEKAHALOVE.DEV")

        assert by_slug is not None
        assert by_hostname is not None
        assert by_slug.id == by_hostname.id

        public_profile = candidate_profile_to_public_dict(by_slug)
        assert public_profile["slug"] == "rebekah-love"
        assert public_profile["updatedAt"]
        assert len(public_profile["facts"]) == 1
        public_fact = public_profile["facts"][0]
        assert public_fact["id"]
        assert public_fact["claim"] == "Public verified fact"
        assert public_fact["category"] == "skill"
        assert public_fact["source"] == "test"
        assert public_fact["visibility"] == "public"
        assert public_fact["verificationStatus"] == "published"
