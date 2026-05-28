from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import jobops_api.command_center as command_center_module
from jobops_api.db.models import Base, CandidateSavedJob, JobPosting, TargetCompany
from jobops_api.db.seed_profile import seed_public_profile
from jobops_api.job_discovery import (
    JobDiscoveryOutput,
    JobDiscoveryRecord,
    JobDiscoveryRequest,
    JobDiscoverySaveResult,
    JobDiscoveryServiceResult,
    build_job_discovery_assistant_message,
    build_job_discovery_model_request,
    extract_grounded_urls,
    job_url_is_grounded,
    list_jobs,
    run_job_discovery,
    save_discovered_jobs,
    save_live_job_source_results,
    LiveJobSourceResult,
    validate_job_discovery_output,
)
from jobops_api.settings import Settings


def test_job_discovery_creates_global_jobs_and_profile_links(tmp_path: Path) -> None:
    engine = create_seeded_engine()

    with Session(engine) as session:
        result = run_job_discovery(
            JobDiscoveryRequest(
                latest_user_message="Find me some jobs to apply to.",
                candidate_profile_slug="rebekah-love",
            ),
            db_session=session,
            settings=make_settings(tmp_path),
        )

        assert result.status_code == 200
        assert result.body["ok"] is True
        assert result.body["result"]["savedCount"] == 2
        assert result.body["result"]["createdGlobalJobCount"] == 2
        assert len(session.scalars(select(JobPosting)).all()) == 2
        assert len(session.scalars(select(CandidateSavedJob)).all()) == 2
        assert len(session.scalars(select(TargetCompany)).all()) == 2

        saved_link = session.scalars(select(CandidateSavedJob).order_by(CandidateSavedJob.added_at.asc())).first()
        assert saved_link is not None
        assert saved_link.added_at is not None
        assert saved_link.status == "saved"
        assert saved_link.fit_summary
        assert saved_link.job.posting_date is not None


def test_job_discovery_rediscovery_reuses_global_job_and_preserves_added_at(tmp_path: Path) -> None:
    engine = create_seeded_engine()

    with Session(engine) as session:
        first = run_job_discovery(
            JobDiscoveryRequest(latest_user_message="Find applied AI engineer jobs.", candidate_profile_slug="rebekah-love"),
            db_session=session,
            settings=make_settings(tmp_path),
        )
        assert first.status_code == 200
        first_links = list(session.scalars(select(CandidateSavedJob).order_by(CandidateSavedJob.id.asc())))
        first_added_at = {link.job.normalized_url: link.added_at for link in first_links}

        second = run_job_discovery(
            JobDiscoveryRequest(latest_user_message="Find applied AI engineer jobs again.", candidate_profile_slug="rebekah-love"),
            db_session=session,
            settings=make_settings(tmp_path),
        )

        assert second.status_code == 200
        assert second.body["result"]["savedCount"] == 0
        assert second.body["result"]["updatedExistingCount"] == 2
        assert second.body["result"]["providerResultCount"] == 2
        assert second.body["result"]["modelSelectedCount"] == 0
        assert second.body["result"]["currentSavedJobCount"] == 2
        assert second.body["result"]["excludedJobUrlCount"] == 2
        assert "already in your Jobs list" in second.body["result"]["assistantMessage"]
        assert len(session.scalars(select(JobPosting)).all()) == 2
        assert len(session.scalars(select(CandidateSavedJob)).all()) == 2
        for link in session.scalars(select(CandidateSavedJob)).all():
            assert link.added_at == first_added_at[link.job.normalized_url]


def test_same_global_job_can_be_saved_by_different_profiles(tmp_path: Path) -> None:
    engine = create_seeded_engine(include_second_profile=True)

    with Session(engine) as session:
        for slug in ["rebekah-love", "alex-love"]:
            result = run_job_discovery(
                JobDiscoveryRequest(latest_user_message="Find remote AI platform roles.", candidate_profile_slug=slug),
                db_session=session,
                settings=make_settings(tmp_path),
            )
            assert result.status_code == 200

        jobs = session.scalars(select(JobPosting)).all()
        links = session.scalars(select(CandidateSavedJob)).all()

        assert len(jobs) == 2
        assert len(links) == 4
        assert len({link.candidate_profile_id for link in links}) == 2
        assert len({link.job_id for link in links}) == 2


def test_saved_job_link_fields_are_profile_specific_and_list_is_scoped() -> None:
    engine = create_seeded_engine(include_second_profile=True)
    with Session(engine) as session:
        profiles = {profile.slug: profile for profile in session.scalars(select(command_center_module.CandidateProfile)).all()}
        output = JobDiscoveryOutput(
            assistantMessage="Found one job.",
            jobs=[
                JobDiscoveryRecord(
                    title="Applied AI Engineer",
                    companyName="Example Civic",
                    jobUrl="https://jobs.example.test/example-civic/applied-ai",
                    fitSummary="Matches applied AI for this profile.",
                    postingDate=None,
                )
            ],
            skippedJobs=[],
            clarifyingQuestions=[],
        )
        first = save_discovered_jobs(
            session,
            candidate_profile=profiles["rebekah-love"],
            discovery_query="Find jobs",
            output=output,
            provider="mock",
            grounding_metadata={},
            web_search_queries=[],
        )
        second = save_discovered_jobs(
            session,
            candidate_profile=profiles["alex-love"],
            discovery_query="Find jobs",
            output=output,
            provider="mock",
            grounding_metadata={},
            web_search_queries=[],
        )
        first.saved_links[0].user_notes = "Private first-user note"
        first.saved_links[0].status = "review"
        second.saved_links[0].user_notes = "Private second-user note"
        session.commit()

        first_payload = list_jobs(session=session, auth=SimpleNamespace(candidate_profile=profiles["rebekah-love"]))
        second_payload = list_jobs(session=session, auth=SimpleNamespace(candidate_profile=profiles["alex-love"]))

    assert len(first_payload) == 1
    assert len(second_payload) == 1
    assert first_payload[0]["job_id"] == second_payload[0]["job_id"]
    assert first_payload[0]["user_notes"] == "Private first-user note"
    assert first_payload[0]["status"] == "review"
    assert second_payload[0]["user_notes"] == "Private second-user note"
    assert "Private second-user note" not in json.dumps(first_payload)


def test_job_discovery_requires_reliable_url_and_allows_null_posting_date() -> None:
    output, warnings = validate_job_discovery_output(
        json.dumps(
            {
                "assistantMessage": "Found jobs.",
                "jobs": [
                    {
                        "title": "No URL Role",
                        "companyName": "Example Civic",
                        "jobUrl": "",
                    },
                    {
                        "title": "Backend AI Engineer",
                        "companyName": "Example Civic",
                        "jobUrl": "https://jobs.example.test/example-civic/backend-ai",
                        "postingDate": None,
                    },
                ],
                "skippedJobs": [],
                "clarifyingQuestions": [],
            }
        )
    )

    assert warnings
    assert [job.title for job in output.jobs] == ["Backend AI Engineer"]
    assert output.jobs[0].posting_date is None
    assert output.skipped_jobs[0].reason == "Skipped invalid or incomplete job result."


def test_job_discovery_request_passes_user_constraints_into_context() -> None:
    request = build_job_discovery_model_request(
        JobDiscoveryRequest(
            latest_user_message=(
                "Find me applied AI jobs, but avoid defense contractors, right-wing political groups, "
                "sports, booze, tobacco, gambling, and crypto."
            ),
            candidate_profile_slug="rebekah-love",
            active_workspace="jobs",
            client_context={"transcript": {"messages": [{"role": "user", "type": "message", "text": "avoid gambling"}]}},
        ),
        current_saved_jobs=[],
        current_saved_companies=[{"name": "CivicActions", "careers_url": "https://civicactions.com/careers"}],
        target_context={"constraints": {"industries": "avoid defense"}},
        private_profile_context={"headline": "Applied AI Engineer"},
        search_grounding_enabled=True,
    )

    user_prompt = request.messages[1].content
    system_prompt = request.messages[0].content
    assert request.task == "job_discovery"
    assert request.search_grounding is True
    assert request.metadata["fresh_search_required"] is True
    assert request.metadata["fresh_search_query_count"] > 0
    assert "current_saved_companies" in system_prompt
    assert "Fresh web search is mandatory" in system_prompt
    assert "exclusions only" in system_prompt
    assert "company's original job posting" in system_prompt
    assert "company-owned posting URL" in system_prompt
    assert "fresh_search_required" in user_prompt
    assert "fresh_search_queries" in user_prompt
    assert "current_saved_jobs_are_exclusions_only" in user_prompt
    assert "avoid defense contractors" in user_prompt
    assert "right-wing political groups" in user_prompt
    assert "avoid gambling" in user_prompt
    assert "CivicActions" in user_prompt
    assert "current_saved_companies" in user_prompt
    assert "private_profile_context" in user_prompt
    saved_job_prompt = build_job_discovery_model_request(
        JobDiscoveryRequest(latest_user_message="Find more jobs.", candidate_profile_slug="rebekah-love"),
        current_saved_jobs=[
            {
                "title": "Existing Role",
                "company_name": "Existing Co",
                "job_url": "https://jobs.example.test/existing?utm_source=old",
                "normalized_url": "https://jobs.example.test/existing",
            }
        ],
        current_saved_companies=[],
        target_context={},
        private_profile_context={},
        search_grounding_enabled=True,
    ).messages[1].content
    assert "do_not_return_job_urls" in saved_job_prompt
    assert "https://jobs.example.test/existing" in saved_job_prompt


def test_model_output_is_not_saved_even_when_search_grounding_mentions_url() -> None:
    engine = create_seeded_engine()
    grounding_metadata = {
        "groundingChunks": [
            {"web": {"uri": "https://company.example/jobs/current-ai-engineer", "title": "Current AI Engineer"}}
        ]
    }
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        output = JobDiscoveryOutput(
            assistantMessage="Found jobs.",
            jobs=[
                JobDiscoveryRecord(
                    title="Current AI Engineer",
                    companyName="Example Company",
                    jobUrl="https://company.example/jobs/current-ai-engineer",
                    sourceUrls=["https://company.example/jobs/current-ai-engineer"],
                ),
                JobDiscoveryRecord(
                    title="Stale AI Engineer",
                    companyName="Example Company",
                    jobUrl="https://company.example/jobs/stale-ai-engineer",
                    sourceUrls=["https://company.example/jobs/stale-ai-engineer"],
                ),
                JobDiscoveryRecord(
                    title="Unsourced AI Engineer",
                    companyName="Example Company",
                    jobUrl="https://company.example/jobs/unsourced-ai-engineer",
                    sourceUrls=[],
                ),
            ],
            skippedJobs=[],
            clarifyingQuestions=[],
        )

        result = save_discovered_jobs(
            session,
            candidate_profile=profile,
            discovery_query="Find jobs",
            output=output,
            provider="gemini",
            grounding_metadata=grounding_metadata,
            web_search_queries=["site:company.example jobs ai engineer"],
            require_grounded_job_urls=True,
        )
        session.commit()

        assert result.saved_links == []
        assert len(result.skipped) == 3
        assert {item.reason_code for item in result.skipped} == {"no_live_source_provenance"}
        assert len(session.scalars(select(JobPosting)).all()) == 0
    assert job_url_is_grounded(
        "https://company.example/jobs/current-ai-engineer",
        ["https://company.example/jobs/current-ai-engineer"],
        extract_grounded_urls(grounding_metadata),
    )


def test_model_only_url_shaped_job_is_not_saved_without_provenance() -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        output = JobDiscoveryOutput(
            assistantMessage="Found jobs.",
            jobs=[
                JobDiscoveryRecord(
                    title="Invented AI Engineer",
                    companyName="Maybe Real",
                    jobUrl="https://maybe-real.example/jobs/ai-engineer",
                    sourceUrls=[],
                )
            ],
            skippedJobs=[],
            clarifyingQuestions=[],
        )

        result = save_discovered_jobs(
            session,
            candidate_profile=profile,
            discovery_query="Find jobs",
            output=output,
            provider="gemini",
            grounding_metadata={},
            web_search_queries=[],
            require_grounded_job_urls=True,
        )

        assert result.saved_links == []
        assert result.skipped[0].reason_code == "no_live_source_provenance"
        assert len(session.scalars(select(JobPosting)).all()) == 0


def test_404_job_url_is_skipped(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", hdrs=None, fp=None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        result = save_live_job_source_results(
            session,
            candidate_profile=profile,
            discovery_query="Find jobs",
            source_results=[
                LiveJobSourceResult(
                    title="Applied AI Engineer",
                    company_name="Closed Co",
                    job_url="https://closed.example/jobs/old",
                    source_provider="test_provider",
                    provenance="provider_result",
                )
            ],
            search_queries_used=["Applied AI Engineer jobs"],
            provider="test_provider",
            verify_urls=True,
        )

        assert result.saved_links == []
        assert result.skipped[0].reason_code == "expired_or_closed"
        assert len(session.scalars(select(JobPosting)).all()) == 0


def test_provider_result_can_be_saved_with_provenance_without_fetch() -> None:
    engine = create_seeded_engine()
    with Session(engine) as session:
        profile = command_center_module.get_candidate_profile_by_slug(session, "rebekah-love")
        assert profile is not None
        result = save_live_job_source_results(
            session,
            candidate_profile=profile,
            discovery_query="Find jobs",
            source_results=[
                LiveJobSourceResult(
                    title="Applied AI Engineer",
                    company_name="Provider Co",
                    job_url="https://provider.example/jobs/applied-ai",
                    source_provider="test_provider",
                    source_result_id="job-123",
                    source_query="Applied AI Engineer jobs",
                    source_url="https://provider.example/jobs/applied-ai",
                    provenance="provider_result",
                    posting_date=None,
                    fit_summary="Provider-backed result.",
                )
            ],
            search_queries_used=["Applied AI Engineer jobs"],
            provider="test_provider",
            verify_urls=False,
        )

        assert len(result.saved_links) == 1
        job = result.saved_links[0].job
        assert job.provenance == "provider_result"
        assert job.source_provider == "test_provider"
        assert job.source_result_id == "job-123"
        assert job.url_verification_status == "provider_unverified"
        assert job.posting_date is None


def test_user_provided_valid_job_url_can_be_saved_when_fetched(monkeypatch, tmp_path: Path) -> None:
    class FakeResponse:
        status = 200
        headers = {"content-type": "text/html; charset=utf-8"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def geturl(self):
            return "https://company.example/jobs/live"

        def read(self, _size):
            return b"<html><title>Live Role</title><body>Live Role at Company Example is open for applications.</body></html>"

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: FakeResponse())
    engine = create_seeded_engine()
    with Session(engine) as session:
        result = run_job_discovery(
            JobDiscoveryRequest(
                latest_user_message="Save this job https://company.example/jobs/live",
                candidate_profile_slug="rebekah-love",
            ),
            db_session=session,
            settings=make_settings(tmp_path, model_provider="gemini", job_discovery_source="none"),
        )

        assert result.status_code == 200
        assert result.body["result"]["savedCount"] == 1
        saved_job = session.scalar(select(JobPosting))
        assert saved_job is not None
        assert saved_job.provenance == "user_url"
        assert saved_job.url_verification_status == "verified"
        assert saved_job.posting_date is None


def test_command_center_job_discovery_returns_saved_job_payload(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(command_center_module, "load_settings", lambda: make_settings(tmp_path))
    engine = create_seeded_engine()

    with Session(engine) as session:
        response = command_center_module.execute_command_center_command(
            command_center_module.CommandCenterCommandRequest(
                command="Find me some jobs to apply to.",
                active_workspace="jobs",
            ),
            session=session,
        )

        assert response.actions[0].type == "job_discovery"
        assert response.actions[0].status == "completed"
        assert response.target_workspace == "jobs"
        assert response.result_payload is not None
        assert response.result_payload["jobDiscoveryMode"] == "mock"
        assert response.result_payload["providerResultCount"] == 2
        assert response.result_payload["jobs"][0]["job_url"].startswith("https://civic-ai-labs.example.test/")
        assert response.result_payload["jobs"][0]["added_at"]
        assert len(session.scalars(select(JobPosting)).all()) == 2
        assert len(session.scalars(select(CandidateSavedJob)).all()) == 2


def test_job_discovery_returns_clear_error_when_live_source_not_configured(tmp_path: Path) -> None:
    engine = create_seeded_engine()
    settings = make_settings(tmp_path, model_provider="gemini", job_discovery_source="none")

    with Session(engine) as session:
        result = run_job_discovery(
            JobDiscoveryRequest(latest_user_message="Find some jobs for me to apply to.", candidate_profile_slug="rebekah-love"),
            db_session=session,
            settings=settings,
        )

        assert result.status_code == 503
        assert result.body["code"] == "live_job_discovery_not_configured"
        assert result.body["error"] == "Live job discovery is not configured. No jobs were saved."
        assert result.body["jobDiscoveryMode"] == "grounded_model_only"
        assert result.body["providerResultCount"] == 0
        assert len(session.scalars(select(JobPosting)).all()) == 0


def test_command_center_job_discovery_passes_actual_chat_transcript(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(command_center_module, "load_settings", lambda: make_settings(tmp_path))
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        command_center_module,
        "run_command_router",
        lambda *args, **kwargs: SimpleNamespace(
            decision=command_center_module.CommandRouterOutput(
                actionType="job_discovery",
                confidence="high",
                targetWorkspace="jobs",
                reason="User asked for concrete job postings.",
            ),
            body={"ok": True},
            unavailable=False,
        ),
    )

    def fake_run_job_discovery(request: JobDiscoveryRequest, **kwargs) -> JobDiscoveryServiceResult:
        captured["client_context"] = request.client_context
        captured["latest_user_message"] = request.latest_user_message
        return JobDiscoveryServiceResult(
            status_code=200,
            body={
                "ok": True,
                "result": {
                    "assistantMessage": "No new jobs were saved.",
                    "jobs": [],
                    "updatedExistingJobs": [],
                    "skippedJobs": [],
                    "savedCount": 0,
                    "updatedExistingCount": 0,
                    "skippedJobCount": 0,
                    "createdGlobalJobCount": 0,
                    "updatedGlobalJobCount": 0,
                },
            },
        )

    monkeypatch.setattr(command_center_module, "run_job_discovery", fake_run_job_discovery)
    engine = create_seeded_engine()

    client_context = {
        "transcript": {
            "messages": [
                {"role": "user", "type": "message", "text": "avoid gambling and crypto"},
                {"role": "assistant", "type": "message", "text": "Got it."},
            ]
        }
    }
    with Session(engine) as session:
        response = command_center_module.execute_command_center_command(
            command_center_module.CommandCenterCommandRequest(
                command="Find me more applied AI jobs.",
                candidate_profile_slug="rebekah-love",
                active_workspace="jobs",
                clientContext=client_context,
            ),
            session=session,
        )

    assert response.actions[0].type == "job_discovery"
    assert captured["latest_user_message"] == "Find me more applied AI jobs."
    assert captured["client_context"] == client_context


def test_job_discovery_assistant_message_reports_duplicate_rediscovery() -> None:
    output = JobDiscoveryOutput(
        assistantMessage="I found 8 promising remote job opportunities and ensured none are duplicates.",
        jobs=[],
        skippedJobs=[],
        clarifyingQuestions=[],
    )
    save_result = JobDiscoverySaveResult(
        saved_links=[],
        updated_existing_links=[object(), object()],  # type: ignore[list-item]
        created_jobs=[],
        updated_jobs=[],
        added_companies=[],
        skipped=[],
    )

    message = build_job_discovery_assistant_message(output, save_result)

    assert "already in your Jobs list" in message
    assert "ensured none are duplicates" not in message


def test_command_center_safe_action_log_metrics_are_counts_only() -> None:
    action = command_center_module.CommandCenterActionResult(
        type="job_discovery",
        status="completed",
        targetWorkspace="jobs",
        title="Discover jobs",
        summary="Done.",
        resultPayload={
            "savedCount": 1,
            "updatedExistingCount": 2,
            "skippedJobCount": 3,
            "currentSavedJobCount": 8,
            "excludedJobUrlCount": 8,
            "currentSavedCompanyCount": 44,
            "skippedReasonCounts": {"Job URL was not supported by fresh search grounding/source URLs.": 3},
            "modelRequest": {"messages": ["private prompt"]},
            "jobs": [{"title": "Private saved job"}],
        },
    )

    metrics = command_center_module.safe_action_log_metrics(action)

    assert metrics == {
        "type": "job_discovery",
        "status": "completed",
        "targetWorkspace": "jobs",
        "savedCount": 1,
        "updatedExistingCount": 2,
        "skippedJobCount": 3,
        "currentSavedJobCount": 8,
        "excludedJobUrlCount": 8,
        "currentSavedCompanyCount": 44,
        "skippedReasons": {"Job URL was not supported by fresh search grounding/source URLs.": 3},
    }


def create_seeded_engine(*, include_second_profile: bool = False):
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
        if include_second_profile:
            seed_public_profile(
                session,
                {
                    "slug": "alex-love",
                    "displayName": "Alex Love",
                    "headline": "AI platform candidate",
                    "summary": "Second private profile.",
                    "profileStatus": "draft",
                },
                hostname="alexlove.dev",
            )
        session.commit()

    return engine


def make_settings(repo_root: Path, *, model_provider: str = "mock", job_discovery_source: str = "mock") -> Settings:
    return Settings(
        app_env="test",
        cheap_model="mock-cheap",
        company_discovery_search_grounding_enabled=True,
        database_url=None,
        default_model="mock-default",
        gemini_api_key=None,
        model_provider=model_provider,
        job_discovery_source=job_discovery_source,
        profile_intake_save_artifacts=False,
        profile_intake_save_raw_text=False,
        repo_root=repo_root,
    )
