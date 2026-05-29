from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import jobops_api.command_center as command_center_module
from jobops_api.company_discovery import (
    CompanyDiscoveryOutput,
    CompanyDiscoveryRecord,
    CompanyDiscoveryRequest,
    build_candidate_target_context,
    build_company_discovery_model_request,
    build_assistant_message,
    company_discovery_validation_failure,
    parse_company_discovery_json,
    run_company_discovery,
    save_model_derived_companies,
    validate_company_discovery_output,
)
from jobops_api.company_canonicalization import ensure_candidate_company_link, upsert_canonical_company
from jobops_api.db.models import Base, CandidateCompany, Company, RoleTarget
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
                review_status="reviewed",
                visibility="private",
                publication_status="published",
                is_active=True,
            )
        )
        add_candidate_company(
            session,
            profile.id,
            "CivicActions",
            website_url="https://civicactions.com",
            derivation_status="user_entered",
            review_status="reviewed",
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

    assert response.actions[0].type == "company_discovery"
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
        saved = list(session.scalars(select(CandidateCompany).join(Company).order_by(Company.name.asc())))
        assert [link.company.name for link in saved] == ["CivicActions", "Higher Ground Labs"]


def test_candidate_target_context_uses_only_published_internal_or_public_targets() -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        session.add_all(
            [
                RoleTarget(
                    candidate_profile_id=profile.id,
                    target_titles=["Draft-only target"],
                    role_families=["Draft"],
                    preferred_locations=["Draft City"],
                    work_modes=["remote"],
                    source="model",
                    review_status="needs_review",
                    visibility="private",
                    publication_status="not_published",
                    is_active=True,
                ),
                RoleTarget(
                    candidate_profile_id=profile.id,
                    target_titles=["Published internal target"],
                    role_families=["Applied AI"],
                    preferred_locations=["Remote US"],
                    work_modes=["remote"],
                    source="model",
                    review_status="reviewed",
                    visibility="private",
                    publication_status="published",
                    is_active=True,
                ),
            ]
        )
        session.commit()

        context = build_candidate_target_context(session, profile)

    assert context["target_role_titles"] == ["Published internal target"]
    assert "Draft-only target" not in json.dumps(context)


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


def test_company_discovery_preserves_model_assistant_message_for_chat() -> None:
    output = CompanyDiscoveryOutput(
        assistantMessage=(
            "**Best pattern:** civic-tech and democracy infrastructure companies looked strongest.\n\n"
            "- Example Civic fits applied AI/platform work.\n"
            "- Verify current openings before prioritizing."
        ),
        companies=[
            CompanyDiscoveryRecord(
                name="Example Civic",
                normalizedName="example civic",
                websiteUrl="https://example.org",
                sourceUrls=["https://example.org"],
            )
        ],
        skippedExistingCompanies=[],
        clarifyingQuestions=[],
    )
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        added = [add_candidate_company(session, profile.id, "Example Civic", website_url="https://example.org")]

    assert build_assistant_message(output, added, []) == output.assistant_message


def test_company_discovery_prompt_tells_model_to_write_chat_answer() -> None:
    request = build_company_discovery_model_request(
        CompanyDiscoveryRequest(
            latest_user_message="Find companies to follow.",
            candidate_profile_slug="rebekah-love",
        ),
        current_saved_companies=[],
        target_context={},
        search_grounding_enabled=True,
    )

    system_prompt = request.messages[0].content
    assert "assistantMessage as the chat answer" in system_prompt
    assert "concise markdown" in system_prompt
    assert "Do not make it a generic save-count receipt" in system_prompt


def test_company_discovery_salvages_valid_records_from_partly_invalid_output() -> None:
    output, warnings = validate_company_discovery_output(
        json.dumps(
            {
                "assistantMessage": "**Found a few options.**",
                "companies": [
                    {
                        "name": "Valid Civic",
                        "normalizedName": "valid civic",
                        "websiteUrl": "https://valid.example",
                        "remotePolicy": "varies",
                        "sourceUrls": [],
                        "unexpectedModelField": "ignored",
                    },
                    {
                        "name": "",
                        "sourceUrls": [],
                    },
                ],
                "skippedExistingCompanies": [],
                "clarifyingQuestions": [],
            }
        )
    )

    assert output.assistant_message == "**Found a few options.**"
    assert [company.name for company in output.companies] == ["Valid Civic"]
    assert output.companies[0].remote_policy == "unknown"
    assert output.companies[0].source_urls == ["https://valid.example"]
    assert warnings


def test_company_discovery_validation_failure_logs_preview(tmp_path: Path, caplog) -> None:
    caplog.set_level(logging.WARNING, logger="jobops_api.company_discovery")
    response = SimpleNamespace(
        finish_reason="STOP",
        model="test-model",
        provider="test-provider",
        text="not json\nwith details that should be previewed",
        metadata={},
        usage=None,
    )
    request = build_company_discovery_model_request(
        CompanyDiscoveryRequest(
            latest_user_message="Find companies to follow.",
            candidate_profile_slug="rebekah-love",
        ),
        current_saved_companies=[],
        target_context={},
        search_grounding_enabled=True,
    )

    result = company_discovery_validation_failure(make_settings(tmp_path), request, response, ["Output is not valid JSON."])

    assert result.status_code == 502
    assert "Company discovery model output validation failed." in caplog.text
    assert caplog.records[-1].response_preview == "not json with details that should be previewed"


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
        add_candidate_company(
            session,
            profile.id,
            "Existing Civic",
            normalized_name="existing civic",
            website_url="https://existing.example",
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

        assert [link.company.name for link in result.added] == ["New Civic"]
        assert len(result.skipped) == 2
        saved = session.scalar(select(CandidateCompany).join(Company).where(Company.name == "New Civic"))
        assert saved is not None
        assert saved.derivation_status == "model_derived"
        assert saved.review_status == "new"
        assert saved.search_queries_used == ["civic tech hiring"]


def test_save_model_derived_companies_reuses_canonical_company_across_profiles() -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        first_profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert first_profile is not None
        second_profile = seed_public_profile(
            session,
            {
                "slug": "second-candidate",
                "displayName": "Second Candidate",
                "headline": "Candidate profile setup in progress",
                "summary": "",
                "profileStatus": "draft",
            },
            hostname="second.example",
        )
        output = CompanyDiscoveryOutput(
            assistantMessage="Added companies.",
            companies=[
                CompanyDiscoveryRecord(
                    name="Shared Civic",
                    normalizedName="shared civic",
                    websiteUrl="https://shared.example",
                    sourceUrls=["https://shared.example"],
                    fitReason="Profile-specific fit.",
                )
            ],
            skippedExistingCompanies=[],
            clarifyingQuestions=[],
        )

        first = save_model_derived_companies(
            session,
            candidate_profile=first_profile,
            discovery_query="Find companies",
            output=output,
            provider="mock",
            grounding_metadata={},
            web_search_queries=[],
        )
        second = save_model_derived_companies(
            session,
            candidate_profile=second_profile,
            discovery_query="Find companies",
            output=output,
            provider="mock",
            grounding_metadata={},
            web_search_queries=[],
        )
        session.commit()

        assert len(first.added) == 1
        assert len(second.added) == 1
        assert len(session.scalars(select(Company)).all()) == 1
        assert len(session.scalars(select(CandidateCompany)).all()) == 2
        assert first.added[0].company_id == second.added[0].company_id


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


def add_candidate_company(
    session: Session,
    candidate_profile_id: str,
    name: str,
    *,
    normalized_name: str | None = None,
    website_url: str | None = None,
    derivation_status: str = "model_derived",
    review_status: str = "new",
) -> CandidateCompany:
    company = upsert_canonical_company(
        session,
        name=name,
        normalized_name=normalized_name or name.casefold(),
        website_url=website_url,
    )
    result = ensure_candidate_company_link(
        session,
        candidate_profile_id=candidate_profile_id,
        company=company,
        derivation_status=derivation_status,
        review_status=review_status,
    )
    return result.link


def make_settings(repo_root: Path) -> Settings:
    return Settings(
        app_env="test",
        cheap_model="mock-cheap",
        company_discovery_search_grounding_enabled=True,
        database_url=None,
        default_model="mock-default",
        gemini_api_key=None,
        model_provider="mock",
        profile_intake_save_artifacts=False,
        profile_intake_save_raw_text=False,
        repo_root=repo_root,
    )
