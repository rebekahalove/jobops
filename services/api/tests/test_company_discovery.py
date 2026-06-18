from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
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
    SkippedExistingCompany,
    archive_company,
    avoid_company,
    build_candidate_target_context,
    build_company_discovery_profile_context,
    build_company_discovery_model_request,
    build_assistant_message,
    company_discovery_validation_failure,
    get_latest_company_discovery_diagnostics,
    parse_company_discovery_json,
    run_company_discovery,
    save_model_derived_companies,
    serialize_company,
    restore_company,
    watch_company,
    validate_company_discovery_output,
)
from jobops_api.company_canonicalization import ensure_candidate_company_link, upsert_canonical_company
from jobops_api.db.models import Application, Base, CandidateCompany, CandidateSavedJob, CommandInteractionLog, Company, JobListing, JobListingSource, ProfileFactDraft, RoleTarget, SkillClaim
from jobops_api.db.seed_profile import seed_public_profile
from jobops_api.model_connector import ModelResponse
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
    assert response.result_payload["companies"][0]["name"] == "Profile-Aligned Example Co"
    assert response.result_payload["companies"][0]["derivation_status"] == "model_derived"
    assert response.result_payload["companies"][0]["review_status"] == "new"
    provider_rows = response.result_payload["providerDiagnostics"]
    assert any(row["stage"] == "company_source" and row["provider"] == "mock" for row in provider_rows)
    assert any(row["stage"] == "persistence" and row["resultSummary"]["savedCompanyCount"] == 2 for row in provider_rows)

    with Session(engine) as session:
        saved = list(session.scalars(select(CandidateCompany).join(Company).order_by(Company.name.asc())))
        assert [link.company.name for link in saved] == ["CivicActions", "Profile-Aligned Example Co", "Second Example Employer"]


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


def test_company_discovery_profile_context_includes_authenticated_profile_drafts() -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        profile.headline = "Painter and installation artist"
        session.add(
            ProfileFactDraft(
                candidate_profile_id=profile.id,
                claim="Creates large-scale textile installations for galleries.",
                fact_type="experience",
                structured_value={},
                source="model",
                confidence="medium",
                suggested_visibility="private",
                review_status="needs_review",
            )
        )
        session.commit()

        context = build_company_discovery_profile_context(profile)

    assert context["profile_basics"]["headline"] == "Painter and installation artist"
    assert context["draft_items"][0]["claim"] == "Creates large-scale textile installations for galleries."


def test_company_discovery_request_uses_search_grounding_and_context() -> None:
    request = build_company_discovery_model_request(
        CompanyDiscoveryRequest(
            latest_user_message="Find civic tech companies.",
            candidate_profile_slug="rebekah-love",
        ),
        current_saved_companies=[{"name": "Existing", "normalized_name": "existing"}],
        target_context={"target_role_titles": ["Applied AI Engineer"]},
        profile_context={"profile_basics": {"headline": "Studio artist"}},
        search_grounding_enabled=True,
    )

    assert request.task == "company_discovery"
    assert request.search_grounding is True
    assert request.response_mime_type is None
    assert request.metadata["current_saved_company_count"] == 1
    assert "Existing" in request.messages[1].content
    assert "Applied AI Engineer" in request.messages[1].content
    assert "Studio artist" in request.messages[1].content
    assert "company_discovery_context" in request.messages[1].content


def test_company_discovery_prompt_has_no_hard_coded_ai_or_civic_defaults() -> None:
    request = build_company_discovery_model_request(
        CompanyDiscoveryRequest(
            latest_user_message="Please find some companies to follow.",
            candidate_profile_slug="artist-profile",
        ),
        current_saved_companies=[],
        target_context={},
        profile_context={"profile_basics": {"headline": "Painter and installation artist"}},
        search_grounding_enabled=True,
    )

    combined_prompt = "\n".join(message.content for message in request.messages)
    assert "Painter and installation artist" in combined_prompt
    assert "Do not default to any specific role, industry, mission, geography" in combined_prompt
    assert "future AI/software roles" not in combined_prompt
    assert "Prefer companies relevant to progressive politics" not in combined_prompt
    assert "Remote US" not in combined_prompt
    assert "Washington, DC" not in combined_prompt
    assert "United States" not in combined_prompt
    assert "San Francisco" not in combined_prompt


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


def test_company_discovery_assistant_message_reports_actual_saved_count() -> None:
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
        message = build_assistant_message(output, added, [])

    assert message == "Saved 1 new company to your Companies list: Example Civic."


def test_company_discovery_assistant_message_reports_partial_additions() -> None:
    output = CompanyDiscoveryOutput(
        assistantMessage="I've identified several companies that align with your skills.",
        companies=[
            CompanyDiscoveryRecord(
                name="Example Civic",
                normalizedName="example civic",
                websiteUrl="https://example.org",
                sourceUrls=["https://example.org"],
            ),
            CompanyDiscoveryRecord(
                name="Duplicate Civic",
                normalizedName="duplicate civic",
                websiteUrl="https://example.org/careers",
                sourceUrls=["https://example.org/careers"],
            ),
        ],
        skippedExistingCompanies=[],
        clarifyingQuestions=[],
    )
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        added = [add_candidate_company(session, profile.id, "Example Civic", website_url="https://example.org")]
        message = build_assistant_message(output, added, [])

    assert message == (
        "Saved 1 new company to your Companies list: Example Civic. "
        "Other model candidates were not added because they did not produce new followed-company links."
    )
    assert "identified several" not in message


def test_company_discovery_assistant_message_reports_no_additions_before_model_claims() -> None:
    output = CompanyDiscoveryOutput(
        assistantMessage="I've identified several companies that align with your skills.",
        companies=[
            CompanyDiscoveryRecord(
                name="Already Followed Studio",
                normalizedName="already followed studio",
                websiteUrl="https://already-followed.example",
                sourceUrls=["https://already-followed.example"],
            )
        ],
        skippedExistingCompanies=[],
        clarifyingQuestions=[],
    )

    message = build_assistant_message(
        output,
        added=[],
        skipped=[SkippedExistingCompany(name="Already Followed Studio", reason="Already followed by this profile.")],
    )

    assert message == "No new companies were added. Skipped 1 already-followed company candidate(s)."
    assert "identified several" not in message


def test_company_discovery_assistant_message_keeps_clarifying_question_response() -> None:
    output = CompanyDiscoveryOutput(
        assistantMessage="Which kind of studios should I prioritize?",
        companies=[],
        skippedExistingCompanies=[],
        clarifyingQuestions=["Which kind of studios should I prioritize?"],
    )

    assert build_assistant_message(output, added=[], skipped=[]) == "Which kind of studios should I prioritize?"


def test_company_discovery_prompt_tells_model_to_write_chat_answer() -> None:
    request = build_company_discovery_model_request(
        CompanyDiscoveryRequest(
            latest_user_message="Find companies to follow.",
            candidate_profile_slug="rebekah-love",
        ),
        current_saved_companies=[],
        target_context={},
        profile_context={},
        search_grounding_enabled=True,
    )

    system_prompt = request.messages[0].content
    assert "assistantMessage as the chat answer" in system_prompt
    assert "concise markdown" in system_prompt
    assert "Do not make it a generic save-count receipt" in system_prompt
    assert "searchQueriesUsed" in system_prompt
    assert "discoveryAngles" in system_prompt


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


def test_company_discovery_salvage_trims_overlong_skipped_companies() -> None:
    output, warnings = validate_company_discovery_output(
        json.dumps(
            {
                "assistantMessage": "Found options, with a noisy duplicate list.",
                "companies": [
                    {
                        "name": "Valid Studio",
                        "normalizedName": "valid studio",
                        "websiteUrl": "https://valid-studio.example",
                        "sourceUrls": ["https://valid-studio.example"],
                    }
                ],
                "skippedExistingCompanies": [
                    {"name": f"Existing Company {index}", "reason": "Already followed."}
                    for index in range(30)
                ],
                "clarifyingQuestions": [],
            }
        )
    )

    assert [company.name for company in output.companies] == ["Valid Studio"]
    assert len(output.skipped_existing_companies) == 25
    assert any("skippedExistingCompanies: trimmed" in warning for warning in warnings)


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
        profile_context={},
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


def test_save_model_derived_companies_does_not_report_global_canonical_matches_as_skips() -> None:
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
        add_candidate_company(session, first_profile.id, "Shared Studio", website_url="https://shared-studio.example")
        session.commit()

        output = CompanyDiscoveryOutput(
            assistantMessage="Found companies.",
            companies=[
                CompanyDiscoveryRecord(
                    name="Shared Studio",
                    normalizedName="shared studio",
                    websiteUrl="https://shared-studio.example",
                    sourceUrls=["https://shared-studio.example"],
                )
            ],
            skippedExistingCompanies=[
                SkippedExistingCompany(name="Model Reported Global Skip", reason="Already exists somewhere.")
            ],
            clarifyingQuestions=[],
        )

        result = save_model_derived_companies(
            session,
            candidate_profile=second_profile,
            discovery_query="Find studios",
            output=output,
            provider="mock",
            grounding_metadata={},
            web_search_queries=[],
        )
        session.commit()

        assert [link.company.name for link in result.added] == ["Shared Studio"]
        assert result.skipped == []
        assert len(session.scalars(select(Company)).all()) == 1
        assert len(session.scalars(select(CandidateCompany)).all()) == 2


def test_save_model_derived_companies_silently_dedupes_repeated_model_candidates() -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        output = CompanyDiscoveryOutput(
            assistantMessage="Found companies.",
            companies=[
                CompanyDiscoveryRecord(
                    name="Repeated Studio",
                    normalizedName="repeated studio",
                    websiteUrl="https://repeated-studio.example",
                    sourceUrls=["https://repeated-studio.example"],
                ),
                CompanyDiscoveryRecord(
                    name="Repeated Studio Careers",
                    normalizedName="repeated studio careers",
                    websiteUrl="https://repeated-studio.example/careers",
                    sourceUrls=["https://repeated-studio.example/careers"],
                ),
            ],
            skippedExistingCompanies=[],
            clarifyingQuestions=[],
        )

        result = save_model_derived_companies(
            session,
            candidate_profile=profile,
            discovery_query="Find studios",
            output=output,
            provider="mock",
            grounding_metadata={},
            web_search_queries=[],
        )
        session.commit()

        assert [link.company.name for link in result.added] == ["Repeated Studio"]
        assert result.skipped == []


def test_mock_provider_path_saves_model_derived_companies(tmp_path: Path) -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        result = run_company_discovery(
            CompanyDiscoveryRequest(
                latest_user_message="Find broad exploratory companies to follow.",
                candidate_profile_slug="rebekah-love",
            ),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    assert result.status_code == 200
    assert result.body["ok"] is True
    assert len(result.body["result"]["companies"]) == 2
    assert result.body["result"]["modelResponse"]["provider"] == "mock"
    assert json.loads(result.body["result"]["modelResponse"]["text"])["companies"][0]["name"] == "Profile-Aligned Example Co"


def test_company_discovery_prompts_for_targets_on_generic_request(tmp_path: Path) -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        result = run_company_discovery(
            CompanyDiscoveryRequest(
                latest_user_message="Find some more companies for me to follow.",
                candidate_profile_slug="rebekah-love",
            ),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    assert result.status_code == 200
    assert result.body["ok"] is True
    assert result.body["result"]["companies"] == []
    assert result.body["result"]["profileTargetsRequired"] is True
    assert result.body["result"]["blockedByTargetPreflight"] is True
    assert result.body["result"]["preflightReason"] == "no_actionable_company_discovery_context"
    assert result.body["result"]["reason"] == "no_actionable_company_discovery_context"
    assert result.body["result"]["contextSignals"] == {
        "detectedUserSearchTerms": [],
        "detectedTargetTitles": [],
        "detectedRoleFamilies": [],
        "detectedHeadline": None,
        "detectedSkillsCount": 0,
        "detectedExperienceSignalsCount": 0,
    }
    assert result.body["result"]["detectedUserSearchTerms"] == []
    assert result.body["result"]["detectedTargetTitles"] == []
    assert result.body["result"]["detectedRoleFamilies"] == []
    assert result.body["result"]["detectedHeadline"] is None
    assert result.body["result"]["detectedSkillsCount"] == 0
    assert result.body["result"]["detectedExperienceSignalsCount"] == 0
    assert result.body["result"]["recentSearchQueries"] == []
    assert result.body["result"]["searchQueriesUsed"] == []
    assert result.body["result"]["discoveryAngles"] == []
    assert result.body["result"]["modelCompanyCount"] == 0
    assert result.body["result"]["duplicateCompanyCount"] == 0
    assert result.body["result"]["invalidCompanyCount"] == 0
    assert result.body["result"]["savedCompanyCount"] == 0
    assert result.body["result"]["zeroNewCompanyReason"] == "targetPreflightBlocked"
    assert "complete your target details" in result.body["result"]["assistantMessage"]


def test_company_discovery_runs_when_current_request_has_useful_search_terms(tmp_path: Path) -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        result = run_company_discovery(
            CompanyDiscoveryRequest(
                latest_user_message="Find ceramic arts studios to follow.",
                candidate_profile_slug="rebekah-love",
            ),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    assert result.status_code == 200
    assert result.body["ok"] is True
    assert result.body["result"].get("blockedByTargetPreflight") is False
    assert result.body["result"]["preflightReason"] is None
    assert result.body["result"]["contextSignals"]["detectedUserSearchTerms"] == ["ceramic", "arts", "studios"]
    assert len(result.body["result"]["companies"]) == 2


def test_company_discovery_allows_generic_request_when_profile_has_target_role(tmp_path: Path) -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        session.add(
            RoleTarget(
                candidate_profile_id=profile.id,
                target_titles=["Museum Educator"],
                role_families=[],
                preferred_locations=[],
                work_modes=[],
                constraints={},
                source="model",
                review_status="reviewed",
                visibility="private",
                publication_status="published",
                is_active=True,
            )
        )
        session.commit()

        result = run_company_discovery(
            CompanyDiscoveryRequest(
                latest_user_message="Find some more companies for me to follow.",
                candidate_profile_slug="rebekah-love",
            ),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    assert result.status_code == 200
    assert result.body["ok"] is True
    assert result.body["result"].get("profileTargetsRequired") is not True
    assert len(result.body["result"]["companies"]) == 2


def test_company_discovery_allows_generic_request_when_profile_has_skills(tmp_path: Path) -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        session.add(
            SkillClaim(
                candidate_profile_id=profile.id,
                skill_name="Ceramic sculpture",
                skill_category="Creative practice",
                verification_status="reviewed",
                publication_status="not_published",
            )
        )
        session.commit()

        result = run_company_discovery(
            CompanyDiscoveryRequest(
                latest_user_message="Find some more companies for me to follow.",
                candidate_profile_slug="rebekah-love",
            ),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    assert result.status_code == 200
    assert result.body["ok"] is True
    assert result.body["result"].get("profileTargetsRequired") is not True
    assert len(result.body["result"]["companies"]) == 2


def test_company_discovery_includes_recent_queries_and_saved_companies_in_context(tmp_path: Path) -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        session.add(
            RoleTarget(
                candidate_profile_id=profile.id,
                target_titles=["Museum Educator"],
                role_families=["Arts Education"],
                preferred_locations=[],
                work_modes=[],
                constraints={},
                source="model",
                review_status="reviewed",
                visibility="private",
                publication_status="published",
                is_active=True,
            )
        )
        link = add_candidate_company(session, profile.id, "Existing Studio", website_url="https://existing-studio.example")
        link.discovery_query = "find ceramic studios"
        link.search_queries_used = ["ceramic studio hiring"]
        session.commit()

        result = run_company_discovery(
            CompanyDiscoveryRequest(
                latest_user_message="Find more companies to follow.",
                candidate_profile_slug="rebekah-love",
            ),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    assert result.status_code == 200
    prompt = result.body["result"]["modelRequest"]["messages"][1]["content"]
    assert "company_discovery_context" in prompt
    assert "find ceramic studios" in prompt
    assert "ceramic studio hiring" in prompt
    assert "Existing Studio" in prompt
    assert "avoid_repeating_recent_discovery_queries" in prompt
    assert result.body["result"]["recentSearchQueries"] == ["find ceramic studios", "ceramic studio hiring"]


def test_company_discovery_allows_explicit_direction_without_saved_targets(tmp_path: Path) -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        result = run_company_discovery(
            CompanyDiscoveryRequest(
                latest_user_message="Find ceramic arts studios to follow.",
                candidate_profile_slug="rebekah-love",
            ),
            db_session=session,
            settings=make_settings(tmp_path),
        )

    assert result.status_code == 200
    assert result.body["ok"] is True
    assert len(result.body["result"]["companies"]) == 2


def test_company_discovery_retries_when_model_returns_zero_companies(tmp_path: Path) -> None:
    connector = SequentialCompanyDiscoveryConnector(
        [
            company_discovery_response("No companies found.", []),
            company_discovery_response(
                "Found a backup company.",
                [
                    {
                        "name": "Backup Studio",
                        "normalizedName": "backup studio",
                        "websiteUrl": "https://backup-studio.example",
                        "sourceUrls": ["https://backup-studio.example"],
                    }
                ],
            ),
        ]
    )
    engine = create_seeded_engine()
    with Session(engine) as session:
        result = run_company_discovery(
            CompanyDiscoveryRequest(
                latest_user_message="Find ceramic arts studios to follow.",
                candidate_profile_slug="rebekah-love",
            ),
            connector=connector,
            db_session=session,
            settings=make_settings(tmp_path),
        )

    assert result.status_code == 200
    assert result.body["ok"] is True
    assert result.body["result"]["companyDiscoveryAttemptCount"] == 2
    assert result.body["result"]["zeroSaveRetryUsed"] is True
    assert [company["name"] for company in result.body["result"]["companies"]] == ["Backup Studio"]
    assert "Saved 1 new company" in result.body["result"]["assistantMessage"]
    assert "previous company-discovery attempt saved zero" in connector.requests[1].messages[-1].content


def test_company_discovery_retries_when_first_pass_only_matches_followed_companies(tmp_path: Path) -> None:
    connector = SequentialCompanyDiscoveryConnector(
        [
            company_discovery_response(
                "Found an existing company.",
                [
                    {
                        "name": "Existing Studio",
                        "normalizedName": "existing studio",
                        "websiteUrl": "https://existing-studio.example",
                        "sourceUrls": ["https://existing-studio.example"],
                    }
                ],
            ),
            company_discovery_response(
                "Found a distinct company.",
                [
                    {
                        "name": "Fresh Studio",
                        "normalizedName": "fresh studio",
                        "websiteUrl": "https://fresh-studio.example",
                        "sourceUrls": ["https://fresh-studio.example"],
                    }
                ],
            ),
        ]
    )
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        add_candidate_company(session, profile.id, "Existing Studio", website_url="https://existing-studio.example")
        session.commit()

        result = run_company_discovery(
            CompanyDiscoveryRequest(
                latest_user_message="Find ceramic arts studios to follow.",
                candidate_profile_slug="rebekah-love",
            ),
            connector=connector,
            db_session=session,
            settings=make_settings(tmp_path),
        )

    assert result.status_code == 200
    assert result.body["ok"] is True
    assert result.body["result"]["companyDiscoveryAttemptCount"] == 2
    assert [company["name"] for company in result.body["result"]["companies"]] == ["Fresh Studio"]
    assert "Existing Studio" in connector.requests[1].messages[-1].content


def test_company_discovery_duplicate_only_result_reports_clear_no_new_reason(tmp_path: Path) -> None:
    duplicate_payload = company_discovery_response(
        "Found an existing company.",
        [
            {
                "name": "Existing Studio",
                "normalizedName": "existing studio",
                "websiteUrl": "https://existing-studio.example",
                "sourceUrls": ["https://existing-studio.example"],
            }
        ],
        search_queries=["ceramic studio hiring"],
        discovery_angles=["ceramic studios"],
    )
    connector = SequentialCompanyDiscoveryConnector([duplicate_payload, duplicate_payload, duplicate_payload])
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        add_candidate_company(session, profile.id, "Existing Studio", website_url="https://existing-studio.example")
        session.commit()

        result = run_company_discovery(
            CompanyDiscoveryRequest(
                latest_user_message="Find ceramic arts studios to follow.",
                candidate_profile_slug="rebekah-love",
            ),
            connector=connector,
            db_session=session,
            settings=make_settings(tmp_path),
        )

    assert result.status_code == 200
    assert result.body["ok"] is True
    assert result.body["result"]["companies"] == []
    assert result.body["result"]["zeroResultReason"] == "allReturnedCompaniesAlreadySaved"
    assert result.body["result"]["zeroNewCompanyReason"] == "allReturnedCompaniesAlreadySaved"
    assert result.body["result"]["modelCompanyCount"] == 3
    assert result.body["result"]["savedCompanyCount"] == 0
    assert result.body["result"]["duplicateCompanyCount"] == 3
    assert result.body["result"]["invalidCompanyCount"] == 0
    assert result.body["result"]["skippedCompanyCount"] == 3
    assert result.body["result"]["searchQueriesUsed"] == ["ceramic studio hiring", "ceramic studios"]
    assert result.body["result"]["discoveryAngles"] == ["ceramic studios"]
    assert "No new companies were added" in result.body["result"]["assistantMessage"]


def test_company_serialization_includes_provider_fields_counts_and_compact_metadata() -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        seed_public_profile(
            session,
            {
                "slug": "other-profile",
                "displayName": "Other Profile",
                "headline": "Other profile",
                "summary": "",
                "profileStatus": "draft",
            },
            hostname="other.example",
        )
        other_profile = command_center_module.get_candidate_profile_by_slug(session, "other-profile")
        assert other_profile is not None

        company = upsert_canonical_company(
            session,
            name="Hightouch",
            normalized_name="hightouch",
            domain="hightouch.com",
            greenhouse_board_token="hightouch",
            ashby_board_url="https://jobs.ashbyhq.com/hightouch",
            lever_slug="hightouch",
            description="Customer data platform.",
        )
        link = ensure_candidate_company_link(
            session,
            candidate_profile_id=profile.id,
            company=company,
            provider_grounding_metadata={
                "provider": "theirstack",
                "technologyNames": ["Python", "Postgres"],
                "rawProviderPayload": {"huge": "do not expose"},
            },
        ).link
        job = JobListing(
            company_id=company.id,
            company_name="Hightouch",
            title="Applied AI Engineer",
            location_display="Remote US",
            remote_work_mode="remote",
            is_active=True,
        )
        session.add(job)
        session.flush()
        session.add(
            JobListingSource(
                job_listing_id=job.id,
                source_provider="greenhouse",
                provider_type="ats_board",
                provider_job_id="123",
            )
        )
        saved_job = CandidateSavedJob(candidate_profile_id=profile.id, job_listing_id=job.id, status="saved")
        other_saved_job = CandidateSavedJob(candidate_profile_id=other_profile.id, job_listing_id=job.id, status="saved")
        session.add_all([saved_job, other_saved_job])
        session.flush()
        session.add_all(
            [
                Application(
                    candidate_profile_id=profile.id,
                    company_id=company.id,
                    saved_job_id=saved_job.id,
                    company_name="Hightouch",
                    job_title="Applied AI Engineer",
                    status="applied",
                ),
                Application(
                    candidate_profile_id=profile.id,
                    company_id=company.id,
                    company_name="Hightouch",
                    job_title="Archived Applied Role",
                    status="applied",
                    archived_at=datetime.now(timezone.utc),
                ),
                Application(
                    candidate_profile_id=profile.id,
                    company_id=company.id,
                    company_name="Hightouch",
                    job_title="Draft Role",
                    status="draft",
                ),
                Application(
                    candidate_profile_id=other_profile.id,
                    company_id=company.id,
                    saved_job_id=other_saved_job.id,
                    company_name="Hightouch",
                    job_title="Applied AI Engineer",
                    status="applied",
                ),
            ]
        )
        session.commit()

        payload = serialize_company(link, session=session, candidate_profile_id=profile.id)

    assert payload["domain"] == "hightouch.com"
    assert payload["greenhouse_board_token"] == "hightouch"
    assert payload["ashby_board_url"] == "https://jobs.ashbyhq.com/hightouch"
    assert payload["lever_slug"] == "hightouch"
    assert payload["can_sync_jobs"] is True
    assert payload["sync_providers"] == ["greenhouse", "ashby", "lever"]
    assert payload["active_job_count"] == 1
    assert payload["saved_job_count"] == 1
    assert payload["application_count"] == 2
    assert payload["open_application_count"] == 1
    assert payload["provider_grounding_metadata_summary"]["provider"] == "theirstack"
    assert payload["provider_grounding_metadata_summary"]["technologyNames"] == ["Python", "Postgres"]
    assert "rawProviderPayload" not in payload["provider_grounding_metadata_summary"]


def test_company_serialization_derives_theirstack_data_origin() -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        company = upsert_canonical_company(session, name="Hightouch", website_url="https://hightouch.com")
        link = ensure_candidate_company_link(
            session,
            candidate_profile_id=profile.id,
            company=company,
            discovered_by="theirstack",
            provider_grounding_metadata={"provider": "theirstack", "rawProviderPayload": {"secret": "nope"}},
        ).link
        payload = serialize_company(link, session=session, candidate_profile_id=profile.id)

    assert payload["discovered_by"] == "theirstack"
    assert payload["discoverySource"] == "theirstack"
    assert payload["discoverySourceLabel"] == "TheirStack"
    assert payload["dataOriginSource"] == "theirstack"
    assert payload["dataOriginSourceType"] == "provider"
    assert payload["dataOriginSourceLabel"] == "TheirStack company search"
    assert "rawProviderPayload" not in json.dumps(payload["provider_grounding_metadata_summary"])


def test_company_serialization_derives_model_grounded_url_origin() -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        company = upsert_canonical_company(
            session,
            name="CivicActions",
            website_url="https://civicactions.com",
            careers_url="https://civicactions.com/careers",
            source_urls=["https://civicactions.com/about"],
        )
        link = ensure_candidate_company_link(
            session,
            candidate_profile_id=profile.id,
            company=company,
            discovered_by="gemini",
            provider_grounding_metadata={"provider": "gemini"},
        ).link
        payload = serialize_company(link, session=session, candidate_profile_id=profile.id)

    assert payload["discoverySource"] == "model_grounded"
    assert payload["discoverySourceLabel"] == "Gemini model-grounded discovery"
    assert payload["dataOriginSource"] == "https://civicactions.com/careers"
    assert payload["dataOriginSourceType"] == "careers_url"
    assert payload["dataOriginSourceLabel"] == "Company careers page"


def test_company_serialization_derives_user_entered_origin() -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        link = add_candidate_company(
            session,
            profile.id,
            "User Co",
            website_url="https://user.example",
            derivation_status="user_entered",
        )
        payload = serialize_company(link, session=session, candidate_profile_id=profile.id)

    assert payload["discoverySource"] == "user_entered"
    assert payload["discoverySourceLabel"] == "User-entered"
    assert payload["dataOriginSource"] == "https://user.example"
    assert payload["dataOriginSourceType"] == "website"
    assert payload["dataOriginSourceLabel"] == "Company website"


def test_latest_company_discovery_diagnostics_returns_model_grounded_audit() -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        log = command_log(
            profile.id,
            result_payload={
                "discoveryAudit": {
                    "sourcePath": "model_grounded_company_discovery",
                    "routerAction": "company_discovery",
                    "sourceProvider": "gemini",
                    "searchGroundingEnabled": True,
                    "modelProvider": "gemini",
                    "modelName": "gemini-test",
                    "savedCompanyCount": 1,
                    "linkedCompanyCount": 1,
                    "duplicateCompanyCount": 0,
                    "skippedCompanyCount": 0,
                    "theirStack": {"checked": True, "enabled": True, "used": False, "skippedReason": "planner_chose_model_grounded"},
                    "firstPartySync": {"attempted": False},
                    "providerDiagnostics": [
                        {
                            "stage": "company_source",
                            "provider": "gemini",
                            "status": "completed",
                            "label": "Gemini model-grounded company discovery",
                            "requestSummary": {"searchGroundingEnabled": True, "authorization": "Bearer should-not-exist"},
                            "resultSummary": {"savedCompanyCount": 1, "rawProviderPayload": {"secret": "should-not-exist"}},
                        }
                    ],
                    "companies": [
                        {
                            "name": "CivicActions",
                            "discoverySource": "model_grounded",
                            "dataOriginSource": "https://civicactions.com/careers",
                            "dataOriginSourceType": "careers_url",
                        }
                    ],
                }
            },
        )
        session.add(log)
        session.commit()

        payload = get_latest_company_discovery_diagnostics(session=session, auth=SimpleNamespace(candidate_profile=profile))

    assert payload["id"] == log.id
    assert payload["sourcePath"] == "model_grounded_company_discovery"
    assert payload["sourceProvider"] == "gemini"
    assert payload["searchGroundingEnabled"] is True
    assert payload["theirStack"]["checked"] is True
    assert payload["theirStack"]["used"] is False
    assert payload["theirStack"]["skippedReason"] == "planner_chose_model_grounded"
    assert payload["providerDiagnostics"][0]["stage"] == "router"
    model_row = next(row for row in payload["providerDiagnostics"] if row["stage"] == "company_source")
    assert model_row["provider"] == "gemini"
    assert model_row["requestSummary"]["searchGroundingEnabled"] is True
    assert "authorization" not in model_row["requestSummary"]
    assert "rawProviderPayload" not in model_row["resultSummary"]
    assert payload["companies"][0]["dataOriginSource"] == "https://civicactions.com/careers"


def test_latest_company_discovery_diagnostics_returns_theirstack_counts_without_secrets() -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        log = command_log(
            profile.id,
            result_payload={
                "linkedCompanyCount": 2,
                "theirstackDiagnostics": {
                    "enabled": True,
                    "requestShape": {
                        "job_filters": "<present>",
                        "limit": 25,
                        "max_pages": 1,
                        "api_key": "should-not-exist",
                        "authorization": "Bearer should-not-exist",
                        "secretToken": "should-not-exist",
                    },
                    "requestedPages": 1,
                    "fetchedPages": 1,
                    "rawCompanyCount": 5,
                    "normalizedCompanyCount": 4,
                    "upsertedCompanyCount": 4,
                    "linkedCandidateCompanyCount": 2,
                },
                "companyEnrichmentPlan": {"useTheirStackCompanySearch": True},
                "companies": [{"name": "Hightouch", "discoverySource": "theirstack", "dataOriginSource": "theirstack"}],
            },
        )
        session.add(log)
        session.commit()

        payload = get_latest_company_discovery_diagnostics(session=session, auth=SimpleNamespace(candidate_profile=profile))

    assert payload["sourcePath"] == "theirstack_company_enrichment"
    assert payload["theirStack"]["checked"] is True
    assert payload["theirStack"]["used"] is True
    assert payload["theirStack"]["rawCompanyCount"] == 5
    assert payload["theirStack"]["requestShape"]["job_filters"] == "<present>"
    assert payload["theirStack"]["requestShape"]["limit"] == 25
    assert payload["theirStack"]["requestShape"]["max_pages"] == 1
    assert "api_key" not in payload["theirStack"]["requestShape"]
    assert "authorization" not in payload["theirStack"]["requestShape"]
    assert "secretToken" not in payload["theirStack"]["requestShape"]
    assert payload["linkedCompanyCount"] == 2
    theirstack_row = next(row for row in payload["providerDiagnostics"] if row["provider"] == "theirstack")
    assert theirstack_row["stage"] == "company_source"
    assert theirstack_row["requestSummary"]["requestShape"]["job_filters"] == "<present>"
    assert "api_key" not in theirstack_row["requestSummary"]["requestShape"]
    assert "secret-theirstack-key" not in json.dumps(payload)
    assert "should-not-exist" not in json.dumps(payload)


def test_latest_company_discovery_diagnostics_explains_legacy_logs() -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        log = command_log(profile.id, result_payload={"companies": []})
        session.add(log)
        session.commit()

        payload = get_latest_company_discovery_diagnostics(session=session, auth=SimpleNamespace(candidate_profile=profile))

    assert payload["providerDiagnostics"][0]["stage"] == "router"
    assert (
        "This command was logged before company discovery diagnostics were added. Run company discovery again to populate detailed diagnostics."
        in payload["diagnosticMessages"]
    )


def test_company_without_supported_ats_is_not_sync_capable() -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        link = add_candidate_company(session, profile.id, "Plain Company", website_url="https://plain.example")
        session.commit()

        payload = serialize_company(link, session=session, candidate_profile_id=profile.id)

    assert payload["can_sync_jobs"] is False
    assert payload["sync_providers"] == []


def test_company_actions_move_between_archived_avoided_and_watch_states() -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        link = add_candidate_company(session, profile.id, "Actionable Co", website_url="https://actionable.example")
        session.commit()
        auth = SimpleNamespace(candidate_profile=profile)

        archived = archive_company(link.id, session=session, auth=auth)
        session.refresh(link)
        assert archived["company"]["archived_at"] is not None
        assert archived["company"]["review_status"] == "new"

        restored = restore_company(link.id, session=session, auth=auth)
        session.refresh(link)
        assert restored["company"]["archived_at"] is None
        assert restored["company"]["review_status"] == "new"

        avoided = avoid_company(link.id, session=session, auth=auth)
        session.refresh(link)
        assert avoided["company"]["archived_at"] is None
        assert avoided["company"]["review_status"] == "avoided"

        archived_avoid = archive_company(link.id, session=session, auth=auth)
        session.refresh(link)
        assert archived_avoid["company"]["archived_at"] is not None
        assert archived_avoid["company"]["review_status"] == "avoided"

        restored_avoid = restore_company(link.id, session=session, auth=auth)
        session.refresh(link)
        assert restored_avoid["company"]["archived_at"] is None
        assert restored_avoid["company"]["review_status"] == "avoided"

        watched = watch_company(link.id, session=session, auth=auth)
        assert watched["company"]["archived_at"] is None
        assert watched["company"]["review_status"] == "reviewed"


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


class SequentialCompanyDiscoveryConnector:
    def __init__(self, responses: list[str], *, provider: str = "mock", model: str = "mock") -> None:
        self.responses = responses
        self.provider = provider
        self.model = model
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        text = self.responses.pop(0)
        return ModelResponse(text=text, provider=self.provider, model=self.model, finish_reason="stop", metadata={})


def company_discovery_response(
    message: str,
    companies: list[dict[str, object]],
    *,
    search_queries: list[str] | None = None,
    discovery_angles: list[str] | None = None,
) -> str:
    return json.dumps(
        {
            "assistantMessage": message,
            "searchQueriesUsed": search_queries or [],
            "discoveryAngles": discovery_angles or [],
            "companies": companies,
            "skippedExistingCompanies": [],
            "clarifyingQuestions": [],
        }
    )


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


def command_log(candidate_profile_id: str, *, result_payload: dict[str, Any], status: str = "completed") -> CommandInteractionLog:
    return CommandInteractionLog(
        user_id="user-1",
        tenant_id="tenant-1",
        candidate_profile_id=candidate_profile_id,
        user_message="find companies to follow",
        route_selected="company_discovery",
        model_provider="mock",
        parsed_action_payload={"actionType": "company_discovery", "confidence": "high"},
        validation_result={
            "commandResponse": {
                "assistant_message": "Done.",
                "actions": [
                    {
                        "type": "company_discovery",
                        "status": status,
                        "targetWorkspace": "companies",
                        "title": "Discover companies",
                        "summary": "Company discovery completed.",
                        "resultPayload": result_payload,
                    }
                ],
                "target_workspace": "companies",
                "result_payload": result_payload,
            }
        },
        action_applied=status in {"completed", "running"},
        final_response="Done.",
    )


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
