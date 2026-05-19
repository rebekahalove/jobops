from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from jobops_api.command_router import (
    CommandRouterRequest,
    build_command_router_context,
    build_command_router_model_request,
    run_command_router,
)
from jobops_api.db.models import Base, RoleTarget, TargetCompany
from jobops_api.db.seed_profile import seed_public_profile
from jobops_api.profiles import get_candidate_profile_by_slug
from jobops_api.settings import Settings


def test_command_router_request_includes_compact_context(tmp_path: Path) -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        session.add(
            RoleTarget(
                candidate_profile_id=profile.id,
                target_titles=["Applied AI Engineer"],
                role_families=["Applied AI"],
                preferred_locations=["Remote US", "Washington, DC"],
                work_modes=["remote"],
                constraints={"domainsOrIndustries": "progressive politics"},
                source="model",
                review_status="needs_review",
                visibility="private",
                publication_status="not_published",
                is_active=True,
            )
        )
        session.add(
            TargetCompany(
                candidate_profile_id=profile.id,
                name="CivicActions",
                normalized_name="civicactions",
                website_url="https://civicactions.com",
                careers_url="https://civicactions.com/careers",
                job_listings_url="https://civicactions.com/jobs",
                source_urls=["https://civicactions.com"],
            )
        )
        session.commit()

        context = build_command_router_context(
            CommandRouterRequest(
                latest_user_message="Update CivicActions job listings URL to https://example.com/jobs",
                active_workspace="companies",
                candidate_profile=profile,
            ),
            db_session=session,
        )
        request = build_command_router_model_request(context)

    assert request.task == "command_router"
    assert request.search_grounding is False
    assert request.response_mime_type == "application/json"
    assert request.temperature == 0
    payload = json.loads(request.messages[1].content)
    router_context = payload["router_context"]
    assert any(action["actionType"] == "company_update" for action in router_context["available_actions"])
    assert router_context["current_saved_companies"][0]["name"] == "CivicActions"
    assert router_context["current_saved_companies"][0]["id"]
    assert router_context["current_saved_companies"][0]["domains"] == ["civicactions.com"]
    assert router_context["target_summary"]["target_role_titles"] == ["Applied AI Engineer"]
    assert router_context["context_caps"]["current_companies"] == 50
    assert "Verified public profile facts" not in request.messages[1].content


def test_mock_command_router_routes_examples(tmp_path: Path) -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        session.add_all(
            [
                TargetCompany(
                    candidate_profile_id=profile.id,
                    name="CivicActions",
                    normalized_name="civicactions",
                    website_url="https://civicactions.com",
                ),
                TargetCompany(
                    candidate_profile_id=profile.id,
                    name="Higher Ground Labs",
                    normalized_name="higher ground labs",
                    website_url="https://highergroundlabs.com",
                ),
            ]
        )
        session.commit()

        cases = [
            ("Update CivicActions job listings URL to https://civicactions.com/careers", "company_update"),
            ("Set the careers URL for Higher Ground Labs to https://highergroundlabs.com/jobs", "company_update"),
            ("Add this job: https://company.com/jobs/123", "add_job_from_url"),
            ("Find me a dozen progressive politics companies who hire AI engineers", "company_discovery"),
            ("I want to be an Applied AI Engineer", "profile_intake"),
            ("My preferred locations are remote US and DC", "profile_intake"),
        ]
        for command, expected_action in cases:
            result = run_command_router(
                CommandRouterRequest(
                    latest_user_message=command,
                    active_workspace=None,
                    candidate_profile=profile,
                ),
                db_session=session,
                settings=make_settings(tmp_path),
            )

            assert result.decision is not None
            assert result.decision.action_type == expected_action
            assert result.decision.confidence == "high"


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


def make_settings(repo_root: Path) -> Settings:
    return Settings(
        app_env="test",
        cheap_model="mock-cheap",
        company_discovery_search_grounding_enabled=True,
        database_url=None,
        default_model="mock-default",
        default_candidate_profile_slug="rebekah-love",
        gemini_api_key=None,
        model_provider="mock",
        profile_intake_save_artifacts=False,
        profile_intake_save_raw_text=False,
        repo_root=repo_root,
    )
