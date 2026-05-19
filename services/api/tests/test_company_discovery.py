from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import jobops_api.command_center as command_center_module
from jobops_api.company_discovery import (
    CompanyDiscoveryOutput,
    CompanyDiscoveryRecord,
    CompanyDiscoveryRequest,
    build_company_discovery_model_request,
    parse_company_discovery_json,
    run_company_discovery,
    save_model_derived_companies,
)
from jobops_api.db.models import Base, RoleTarget, TargetCompany
from jobops_api.db.seed_profile import seed_public_profile
from jobops_api.settings import Settings


def test_command_center_executes_company_discovery_with_context(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(command_center_module, "load_settings", lambda: make_settings(tmp_path))
    engine = create_seeded_engine()

    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        session.add(
            RoleTarget(
                candidate_profile_id=profile.id,
                target_titles=["Applied AI Engineer", "Senior Software Engineer"],
                role_families=["Applied AI", "Backend Engineering"],
                preferred_locations=["Remote US", "Washington, DC"],
                work_modes=["remote"],
                constraints={"domainsOrIndustries": "progressive politics, civic tech"},
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
                derivation_status="user_entered",
                review_status="reviewed",
            )
        )
        session.commit()

    with Session(engine) as session:
        response = command_center_module.execute_command_center_command(
            command_center_module.CommandCenterCommandRequest(
                command=(
                    "Find me a dozen companies operating in the progressive politics space who hire "
                    "AI engineers or senior software engineers."
                ),
                active_workspace="companies",
            ),
            session=session,
        )

    assert response.actions[0].type == "follow_company"
    assert response.actions[0].status == "completed"
    assert response.target_workspace == "companies"
    assert response.result_payload is not None
    assert response.result_payload["modelRequest"]["task"] == "company_discovery"
    assert response.result_payload["modelRequest"]["searchGrounding"] is True
    user_prompt = response.result_payload["modelRequest"]["messages"][1]["content"]
    assert "current_saved_companies" in user_prompt
    assert "CivicActions" in user_prompt
    assert "candidate_target_context" in user_prompt
    assert "Applied AI Engineer" in user_prompt
    assert response.result_payload["companies"][0]["name"] == "Higher Ground Labs"
    assert response.result_payload["companies"][0]["derivation_status"] == "model_derived"
    assert response.result_payload["companies"][0]["review_status"] == "new"

    with Session(engine) as session:
        saved = list(session.scalars(select(TargetCompany).order_by(TargetCompany.name.asc())))
        assert [company.name for company in saved] == ["CivicActions", "Higher Ground Labs"]


def test_company_discovery_request_uses_search_grounding_and_context() -> None:
    request = build_company_discovery_model_request(
        CompanyDiscoveryRequest(
            latest_user_message="Find civic tech companies.",
            candidate_profile_slug="rebekah-love",
        ),
        current_saved_companies=[{"name": "Existing", "normalized_name": "existing"}],
        target_context={"target_role_titles": ["Applied AI Engineer"]},
        search_grounding_enabled=True,
    )

    assert request.task == "company_discovery"
    assert request.search_grounding is True
    assert request.response_mime_type is None
    assert request.metadata["current_saved_company_count"] == 1
    assert "Existing" in request.messages[1].content
    assert "Applied AI Engineer" in request.messages[1].content


def test_parse_and_validate_company_discovery_output() -> None:
    parsed = parse_company_discovery_json(
        """```json
        {
          "assistantMessage": "Added companies.",
          "companies": [
            {
              "name": "Example Civic Tech",
              "normalizedName": "example civic tech",
              "websiteUrl": "https://example.org",
              "careersUrl": null,
              "jobListingsUrl": null,
              "description": "Builds civic software.",
              "headquartersCity": null,
              "headquartersCountry": "United States",
              "operatingCountries": ["United States"],
              "hiringLocations": [],
              "remotePolicy": "unknown",
              "roleFitTags": ["Applied AI"],
              "missionFitTags": ["Civic tech"],
              "fitReason": "Relevant mission.",
              "sourceUrls": ["https://example.org"],
              "sourceSummary": "Source supports civic focus.",
              "dataConfidence": "medium",
              "notes": null
            }
          ],
          "skippedExistingCompanies": [],
          "clarifyingQuestions": []
        }
        ```"""
    )
    output = CompanyDiscoveryOutput.model_validate(parsed)

    assert output.assistant_message == "Added companies."
    assert output.companies[0].website_url == "https://example.org"
    assert output.companies[0].source_urls == ["https://example.org"]


def test_company_discovery_normalizes_null_remote_policy_to_unknown() -> None:
    record = CompanyDiscoveryRecord(
        name="Example Civic Tech",
        normalizedName="example civic tech",
        websiteUrl="https://example.org",
        remotePolicy=None,
        sourceUrls=["https://example.org"],
    )

    assert record.remote_policy == "unknown"


def test_save_model_derived_companies_skips_normalized_name_and_domain_duplicates() -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        session.add(
            TargetCompany(
                candidate_profile_id=profile.id,
                name="Existing Civic",
                normalized_name="existing civic",
                website_url="https://existing.example",
            )
        )
        session.commit()

        output = CompanyDiscoveryOutput(
            assistantMessage="Added companies.",
            companies=[
                CompanyDiscoveryRecord(
                    name="Existing Civic",
                    normalizedName="existing civic",
                    websiteUrl="https://new.example",
                    sourceUrls=["https://new.example"],
                ),
                CompanyDiscoveryRecord(
                    name="Different Name",
                    normalizedName="different name",
                    websiteUrl="https://existing.example/about",
                    sourceUrls=["https://existing.example/about"],
                ),
                CompanyDiscoveryRecord(
                    name="New Civic",
                    normalizedName="new civic",
                    websiteUrl="https://new-civic.example",
                    sourceUrls=["https://new-civic.example"],
                ),
            ],
            skippedExistingCompanies=[],
            clarifyingQuestions=[],
        )
        result = save_model_derived_companies(
            session,
            candidate_profile=profile,
            discovery_query="Find companies",
            output=output,
            provider="mock",
            grounding_metadata={"webSearchQueries": ["civic tech hiring"]},
            web_search_queries=["civic tech hiring"],
        )
        session.commit()

        assert [company.name for company in result.added] == ["New Civic"]
        assert len(result.skipped) == 2
        saved = session.scalar(select(TargetCompany).where(TargetCompany.name == "New Civic"))
        assert saved is not None
        assert saved.derivation_status == "model_derived"
        assert saved.review_status == "new"
        assert saved.search_queries_used == ["civic tech hiring"]


def test_mock_provider_path_saves_model_derived_companies(tmp_path: Path) -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        result = run_company_discovery(
            CompanyDiscoveryRequest(
                latest_user_message="Find progressive politics companies to follow.",
                candidate_profile_slug="rebekah-love",
            ),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    assert result.status_code == 200
    assert result.body["ok"] is True
    assert len(result.body["result"]["companies"]) == 2
    assert result.body["result"]["modelResponse"]["provider"] == "mock"
    assert json.loads(result.body["result"]["modelResponse"]["text"])["companies"][0]["name"] == "CivicActions"


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
