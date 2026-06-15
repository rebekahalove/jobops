from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import jobops_api.command_center as command_center_module
from jobops_api.company_discovery import CompanyDiscoveryRequest, run_company_discovery
from jobops_api.company_enrichment import (
    COMPANY_ENRICHMENT_PLANNER_SYSTEM_PROMPT,
    MAX_THEIRSTACK_PLAN_LIMIT,
    MAX_THEIRSTACK_PLAN_PAGES,
    ModelPlannedCompanyEnrichmentService,
    build_company_enrichment_plan_request,
    build_company_enrichment_context,
    parse_company_enrichment_plan,
)
from jobops_api.company_sources.theirstack.models import TheirStackCompanySearchDiagnostics, TheirStackCompanySearchResult
from jobops_api.company_canonicalization import ensure_candidate_company_link, upsert_canonical_company
from jobops_api.db.models import Base, CandidateCompany, CandidateSavedJob, Company, JobListing, JobSyncRun, RoleTarget
from jobops_api.db.seed_profile import seed_public_profile
from jobops_api.model_connector import ModelResponse
from jobops_api.settings import Settings


def test_company_enrichment_prompt_supports_greenhouse_and_forbids_defaults() -> None:
    assert "companies with Greenhouse boards" in COMPANY_ENRICHMENT_PLANNER_SYSTEM_PROMPT
    assert "TheirStack indicates are hiring for the user's target work" in COMPANY_ENRICHMENT_PLANNER_SYSTEM_PROMPT
    assert "ordinary saved-jobs ranking" in COMPANY_ENRICHMENT_PLANNER_SYSTEM_PROMPT
    assert "Do not add hardcoded backend defaults" in COMPANY_ENRICHMENT_PLANNER_SYSTEM_PROMPT


def test_company_enrichment_plan_parses_theirstack_search_for_target_role(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    context = json.dumps(
        {
            "latest_user_message": "Find companies hiring for product marketing.",
            "candidate_target_context": {"target_role_titles": ["Product Marketing Manager"]},
        }
    )

    plan, issues = parse_company_enrichment_plan(
        json.dumps(
            {
                "useTheirStackCompanySearch": True,
                "rationale": "The user asked for company hiring-signal leads.",
                "linkDiscoveredCompaniesToProfile": True,
                "requireGreenhouse": False,
                "hiringSignalTerms": ["Product Marketing Manager"],
                "search": {
                    "jobFilters": {"job_title_pattern_or": ["Product Marketing Manager"]},
                    "companyDescriptionPatternOr": ["product marketing"],
                    "limit": 200,
                    "maxPages": 10,
                },
            }
        ),
        settings=settings,
        context_text=context,
    )

    assert plan.use_theirstack_company_search is True
    assert plan.search.job_filters["job_title_pattern_or"] == ["Product Marketing Manager"]
    assert plan.search.company_description_pattern_or == ("product marketing",)
    assert plan.search.limit == MAX_THEIRSTACK_PLAN_LIMIT
    assert plan.search.max_pages == MAX_THEIRSTACK_PLAN_PAGES
    assert {issue["code"] for issue in issues} >= {"theirstack_limit_clamped", "theirstack_max_pages_clamped"}


def test_company_enrichment_plan_sets_require_greenhouse_for_greenhouse_request(tmp_path: Path) -> None:
    plan, issues = parse_company_enrichment_plan(
        json.dumps(
            {
                "useTheirStackCompanySearch": True,
                "rationale": "The user asked for Greenhouse company leads.",
                "requireGreenhouse": True,
                "search": {"companyDescriptionPatternOr": ["greenhouse"]},
            }
        ),
        settings=make_settings(tmp_path),
        context_text=json.dumps({"latest_user_message": "Find companies with Greenhouse boards."}),
    )

    assert plan.use_theirstack_company_search is True
    assert plan.require_greenhouse is True
    assert issues == []


def test_company_enrichment_plan_rejects_saved_jobs_and_direct_url_intents(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    raw_plan = json.dumps(
        {
            "useTheirStackCompanySearch": True,
            "search": {"companyDescriptionPatternOr": ["marketing"]},
        }
    )

    jobs_plan, jobs_issues = parse_company_enrichment_plan(
        raw_plan,
        settings=settings,
        context_text=json.dumps({"latest_user_message": "Which jobs should I apply to today?"}),
    )
    url_plan, url_issues = parse_company_enrichment_plan(
        raw_plan,
        settings=settings,
        context_text=json.dumps({"latest_user_message": "Save this job https://job-boards.greenhouse.io/acme/jobs/1"}),
    )

    assert jobs_plan.use_theirstack_company_search is False
    assert url_plan.use_theirstack_company_search is False
    assert jobs_issues[0]["code"] == "wrong_intent_for_theirstack"
    assert url_issues[0]["code"] == "wrong_intent_for_theirstack"


def test_disabled_theirstack_plan_returns_unavailable_without_client_call(tmp_path: Path) -> None:
    engine = create_seeded_engine()
    client = FakeTheirStackClient([])
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        service = ModelPlannedCompanyEnrichmentService(
            session=session,
            settings=make_settings(tmp_path, api_key=None, enabled=False),
            connector=StaticPlanConnector(theirstack_plan({"companyDescriptionPatternOr": ["marketing"]})),
            theirstack_client=client,
        )

        result = service.run(
            candidate_profile=profile,
            latest_user_message="Find marketing companies.",
            current_saved_companies=[],
            target_context={"target_role_titles": ["Product Marketing Manager"]},
            profile_context={},
            discovery_context={},
        )

    assert result.handled is True
    assert result.body["result"]["zeroResultReason"] == "clarificationNeeded"
    assert client.requests == []


def test_non_ai_profiles_do_not_get_ai_or_llm_filters(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    context = json.dumps(
        {
            "latest_user_message": "Find companies hiring for nurse practitioner work.",
            "candidate_target_context": {"target_role_titles": ["Nurse Practitioner"], "domains_or_industries": "healthcare"},
        }
    )

    plan, issues = parse_company_enrichment_plan(
        json.dumps(
            {
                "useTheirStackCompanySearch": True,
                "hiringSignalTerms": ["Nurse Practitioner", "LLM"],
                "search": {
                    "jobFilters": {"job_title_pattern_or": ["Nurse Practitioner", "AI Engineer"]},
                    "companyDescriptionPatternOr": ["healthcare", "Applied AI"],
                    "companyKeywordSlugOr": ["artificial-intelligence"],
                },
            }
        ),
        settings=settings,
        context_text=context,
    )

    body = json.dumps(plan.search.to_api_body())
    assert "Nurse Practitioner" in body
    assert "healthcare" in body
    assert "AI Engineer" not in body
    assert "Applied AI" not in body
    assert "LLM" not in json.dumps(plan.hiring_signal_terms)
    assert "artificial-intelligence" not in body
    assert any(issue["code"] == "ungrounded_filter_removed" for issue in issues)


def test_company_enrichment_model_request_has_no_hardcoded_role_filters(tmp_path: Path) -> None:
    context = build_company_enrichment_context(
        latest_user_message="Find more companies for my saved companies list.",
        current_saved_companies=[],
        target_context={"target_role_titles": ["Product Marketing Manager"]},
        profile_context={"profile_basics": {"headline": "Product marketer"}},
        discovery_context={},
        settings=make_settings(tmp_path),
    )

    request = build_company_enrichment_plan_request(context)
    prompt = "\n".join(message.content for message in request.messages)

    assert request.task == "company_enrichment_planner"
    assert "Product Marketing Manager" in prompt
    assert "job_title_pattern_or=[\"Applied AI Engineer\"" not in prompt
    assert "artificial-intelligence" not in prompt


def test_model_planned_theirstack_enrichment_links_companies_and_reports_ats_counts(tmp_path: Path) -> None:
    engine = create_seeded_engine()
    client = FakeTheirStackClient(
        [
            theirstack_payload("Greenhouse Co", domain="greenhouse.example", job_url="https://job-boards.greenhouse.io/greenhouseco/jobs/1"),
            theirstack_payload("Ashby Co", domain="ashby.example", job_url="https://jobs.ashbyhq.com/ashbyco/1"),
            theirstack_payload("Lever Co", domain="lever.example", job_url="https://jobs.lever.co/leverco/1"),
        ]
    )
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        service = ModelPlannedCompanyEnrichmentService(
            session=session,
            settings=make_settings(tmp_path),
            connector=StaticPlanConnector(
                theirstack_plan(
                    {"jobFilters": {"job_title_pattern_or": ["Product Marketing Manager"]}},
                    terms=["Product Marketing Manager"],
                )
            ),
            theirstack_client=client,
        )

        result = service.run(
            candidate_profile=profile,
            latest_user_message="Find companies hiring for product marketing.",
            current_saved_companies=[],
            target_context={"target_role_titles": ["Product Marketing Manager"]},
            profile_context={},
            discovery_context={},
        )
        session.commit()

    payload = result.body["result"]
    with Session(engine) as session:
        assert result.handled is True
        assert payload["linkedCompanyCount"] == 3
        assert payload["greenhouseBoardTokenCount"] == 1
        assert payload["ashbyBoardUrlCount"] == 1
        assert payload["leverSlugCount"] == 1
        assert payload["requiresFirstPartySyncForVerification"] is True
        assert "TheirStack returned" in payload["assistantMessage"]
        assert "not synced those boards yet" in payload["assistantMessage"]
        assert len(session.scalars(select(Company)).all()) == 3
        assert len(session.scalars(select(CandidateCompany)).all()) == 3
        assert len(session.scalars(select(JobListing)).all()) == 0
        assert len(session.scalars(select(CandidateSavedJob)).all()) == 0
        assert len(session.scalars(select(JobSyncRun)).all()) == 0


def test_greenhouse_required_enrichment_reports_only_greenhouse_matches(tmp_path: Path) -> None:
    engine = create_seeded_engine()
    client = FakeTheirStackClient(
        [
            theirstack_payload("Greenhouse Co", domain="greenhouse.example", job_url="https://job-boards.greenhouse.io/greenhouseco/jobs/1"),
            theirstack_payload("Plain Co", domain="plain.example", job_url="https://example.myworkdayjobs.com/plain"),
        ]
    )
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        service = ModelPlannedCompanyEnrichmentService(
            session=session,
            settings=make_settings(tmp_path),
            connector=StaticPlanConnector(
                theirstack_plan(
                    {"companyDescriptionPatternOr": ["Greenhouse"]},
                    require_greenhouse=True,
                )
            ),
            theirstack_client=client,
        )

        result = service.run(
            candidate_profile=profile,
            latest_user_message="Find companies with Greenhouse boards.",
            current_saved_companies=[],
            target_context={},
            profile_context={},
            discovery_context={},
        )
        session.commit()

    payload = result.body["result"]
    with Session(engine) as session:
        assert payload["rawCompanyCount"] == 2
        assert payload["normalizedCompanyCount"] == 2
        assert payload["upsertedCompanyCount"] == 2
        assert payload["linkedCompanyCount"] == 1
        assert payload["filteredNoGreenhouseTokenCount"] == 1
        assert payload["greenhouseBoardTokenCount"] == 1
        assert [company["name"] for company in payload["companies"]] == ["Greenhouse Co"]
        assert "added only companies with Greenhouse board tokens as leads" in payload["assistantMessage"]
        assert "filtered out 1 TheirStack company without Greenhouse board tokens" in payload["assistantMessage"]
        assert [link.company.name for link in session.scalars(select(CandidateCompany)).all()] == ["Greenhouse Co"]
        assert sorted(company.name for company in session.scalars(select(Company)).all()) == ["Greenhouse Co", "Plain Co"]


def test_supported_ats_required_links_only_supported_ats_companies(tmp_path: Path) -> None:
    engine = create_seeded_engine()
    client = FakeTheirStackClient(
        [
            theirstack_payload("Greenhouse Co", domain="greenhouse.example", job_url="https://job-boards.greenhouse.io/greenhouseco/jobs/1"),
            theirstack_payload("Ashby Co", domain="ashby.example", job_url="https://jobs.ashbyhq.com/ashbyco/1"),
            theirstack_payload("Lever Co", domain="lever.example", job_url="https://jobs.lever.co/leverco/1"),
            theirstack_payload("Plain Workday Co", domain="plain.example", job_url="https://example.myworkdayjobs.com/plain"),
        ]
    )
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        service = ModelPlannedCompanyEnrichmentService(
            session=session,
            settings=make_settings(tmp_path),
            connector=StaticPlanConnector(
                theirstack_plan(
                    {"companyDescriptionPatternOr": ["hiring"]},
                    require_supported_ats=True,
                )
            ),
            theirstack_client=client,
        )

        result = service.run(
            candidate_profile=profile,
            latest_user_message="Find companies with supported ATS metadata.",
            current_saved_companies=[],
            target_context={},
            profile_context={},
            discovery_context={},
        )
        session.commit()

    payload = result.body["result"]
    with Session(engine) as session:
        assert payload["rawCompanyCount"] == 4
        assert payload["normalizedCompanyCount"] == 4
        assert payload["upsertedCompanyCount"] == 4
        assert payload["linkedCompanyCount"] == 3
        assert payload["filteredNoSupportedAtsCount"] == 1
        assert payload["filteredNoGreenhouseTokenCount"] == 0
        assert payload["greenhouseBoardTokenCount"] == 1
        assert payload["ashbyBoardUrlCount"] == 1
        assert payload["leverSlugCount"] == 1
        assert "supported ATS metadata" in payload["assistantMessage"]
        assert "filtered out 1 TheirStack company without supported ATS metadata" in payload["assistantMessage"]
        assert sorted(company.name for company in session.scalars(select(Company)).all()) == [
            "Ashby Co",
            "Greenhouse Co",
            "Lever Co",
            "Plain Workday Co",
        ]
        assert sorted(link.company.name for link in session.scalars(select(CandidateCompany)).all()) == [
            "Ashby Co",
            "Greenhouse Co",
            "Lever Co",
        ]
        assert len(session.scalars(select(JobListing)).all()) == 0
        assert len(session.scalars(select(CandidateSavedJob)).all()) == 0
        assert len(session.scalars(select(JobSyncRun)).all()) == 0


def test_model_planned_enrichment_dedupes_existing_link_and_preserves_metadata(tmp_path: Path) -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        company = upsert_canonical_company(
            session,
            name="Human Reviewed Co",
            domain="reviewed.example",
            description="Human reviewed description.",
            source_summary="Human reviewed source.",
            greenhouse_board_token="reviewed",
        )
        ensure_candidate_company_link(
            session,
            candidate_profile_id=profile.id,
            company=company,
            review_status="reviewed",
            derivation_status="user_entered",
        )
        session.commit()

    client = FakeTheirStackClient(
        [
            theirstack_payload(
                "Fallback Co",
                domain="reviewed.example",
                description="Weaker provider description.",
                job_url="https://job-boards.greenhouse.io/reviewed/jobs/1",
            )
        ]
    )
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        service = ModelPlannedCompanyEnrichmentService(
            session=session,
            settings=make_settings(tmp_path),
            connector=StaticPlanConnector(theirstack_plan({"companyDomainOr": ["reviewed.example"]})),
            theirstack_client=client,
        )

        service.run(
            candidate_profile=profile,
            latest_user_message="Find companies like reviewed.example.",
            current_saved_companies=[],
            target_context={},
            profile_context={},
            discovery_context={},
        )
        session.commit()

    with Session(engine) as session:
        companies = list(session.scalars(select(Company)))
        links = list(session.scalars(select(CandidateCompany)))
        assert len(companies) == 1
        assert len(links) == 1
        assert companies[0].name == "Human Reviewed Co"
        assert companies[0].description == "Human reviewed description."
        assert companies[0].source_summary == "Human reviewed source."
        assert links[0].review_status == "reviewed"


def test_run_company_discovery_uses_model_planned_theirstack_when_planned(tmp_path: Path) -> None:
    engine = create_seeded_engine()
    client = FakeTheirStackClient(
        [theirstack_payload("Greenhouse Co", domain="greenhouse.example", job_url="https://job-boards.greenhouse.io/greenhouseco/jobs/1")]
    )
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        session.add(
            RoleTarget(
                candidate_profile_id=profile.id,
                target_titles=["Product Marketing Manager"],
                role_families=["Marketing"],
                publication_status="published",
                visibility="private",
                is_active=True,
            )
        )
        session.commit()

        result = run_company_discovery(
            CompanyDiscoveryRequest(
                latest_user_message="Find companies using Greenhouse that are hiring for product marketing.",
                candidate_profile_slug="rebekah-love",
            ),
            connector=StaticPlanConnector(
                theirstack_plan(
                    {"jobFilters": {"job_title_pattern_or": ["Product Marketing Manager"]}},
                    require_greenhouse=True,
                    terms=["Product Marketing Manager"],
                )
            ),
            theirstack_client=client,
            db_session=session,
            settings=make_settings(tmp_path),
            candidate_profile=profile,
        )

    payload = result.body["result"]
    assert result.status_code == 200
    assert payload["linkedCompanyCount"] == 1
    assert payload["greenhouseBoardTokenCount"] == 1
    assert payload["companyEnrichmentPlan"]["useTheirStackCompanySearch"] is True
    assert client.requests


class StaticPlanConnector:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        return ModelResponse(
            text=json.dumps(self.response),
            provider="mock",
            model="mock",
            finish_reason="stop",
            metadata={},
        )


class FakeTheirStackClient:
    def __init__(self, companies: list[dict[str, Any]]) -> None:
        self.companies = companies
        self.requests = []

    def search_companies(self, request):
        self.requests.append(request)
        return TheirStackCompanySearchResult(
            status="completed",
            companies=tuple(self.companies),
            diagnostics=TheirStackCompanySearchDiagnostics(
                enabled=True,
                requested_pages=request.max_pages or 1,
                fetched_pages=1,
                raw_company_count=len(self.companies),
                request_shape=request.sanitized_shape(),
            ),
        )


def theirstack_plan(
    search: dict[str, Any],
    *,
    terms: list[str] | None = None,
    require_supported_ats: bool | None = None,
    require_greenhouse: bool = False,
) -> dict[str, Any]:
    supported_ats = require_greenhouse if require_supported_ats is None else require_supported_ats
    return {
        "useTheirStackCompanySearch": True,
        "rationale": "The user asked for company hiring-signal leads.",
        "linkDiscoveredCompaniesToProfile": True,
        "requireSupportedAts": supported_ats,
        "requireGreenhouse": require_greenhouse,
        "hiringSignalTerms": terms or [],
        "hiringSignalSource": "theirstack",
        "requiresFirstPartySyncForVerification": True,
        "search": search,
        "clarifyingQuestions": [],
    }


def theirstack_payload(
    name: str,
    *,
    domain: str,
    job_url: str,
    description: str = "Provider company description.",
) -> dict[str, Any]:
    return {
        "name": name,
        "domain": domain,
        "description": description,
        "num_jobs_found": 7,
        "jobs_found": [{"url": job_url}],
    }


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


def make_settings(
    repo_root: Path,
    *,
    api_key: str | None = "secret-theirstack-key",
    enabled: bool = True,
) -> Settings:
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
        theirstack_api_key=api_key,
        theirstack_company_search_enabled=enabled,
        theirstack_company_search_limit=25,
        theirstack_company_search_max_pages=1,
    )
