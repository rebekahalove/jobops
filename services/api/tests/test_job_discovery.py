from __future__ import annotations

import json
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
    validate_job_discovery_output,
)
from jobops_api.model_connector import ModelResponse
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
        assert second.body["result"]["modelJobCount"] == 2
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


def test_job_discovery_requires_grounded_exact_source_url_before_saving() -> None:
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

        assert [link.job.title for link in result.saved_links] == ["Current AI Engineer"]
        assert len(result.skipped) == 2
    assert job_url_is_grounded(
        "https://company.example/jobs/current-ai-engineer",
        ["https://company.example/jobs/current-ai-engineer"],
        extract_grounded_urls(grounding_metadata),
    )


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
        assert response.result_payload["modelRequest"]["task"] == "job_discovery"
        assert response.result_payload["jobs"][0]["job_url"].startswith("https://jobs.example.test/")
        assert response.result_payload["jobs"][0]["added_at"]
        assert len(session.scalars(select(JobPosting)).all()) == 2
        assert len(session.scalars(select(CandidateSavedJob)).all()) == 2


def test_job_discovery_retries_with_compact_request_after_truncation(tmp_path: Path) -> None:
    class TruncatingThenValidConnector:
        def __init__(self) -> None:
            self.requests: list[Any] = []

        def generate(self, request):
            self.requests.append(request)
            if len(self.requests) == 1:
                return ModelResponse(
                    text='{"assistantMessage":"Found jobs","jobs":[',
                    provider="mock",
                    model="mock",
                    finish_reason="MAX_TOKENS",
                    metadata={},
                )
            return ModelResponse(
                text=json.dumps(
                    {
                        "assistantMessage": "Saved one compact retry result.",
                        "jobs": [
                            {
                                "title": "Applied AI Engineer",
                                "companyName": "Compact Civic",
                                "jobUrl": "https://jobs.example.test/compact-civic/applied-ai",
                                "sourceUrls": ["https://jobs.example.test/compact-civic/applied-ai"],
                                "fitSummary": "Matches applied AI platform work.",
                            }
                        ],
                        "skippedJobs": [],
                        "clarifyingQuestions": [],
                    }
                ),
                provider="mock",
                model="mock",
                finish_reason="STOP",
                metadata={},
            )

    engine = create_seeded_engine()
    connector = TruncatingThenValidConnector()

    with Session(engine) as session:
        result = run_job_discovery(
            JobDiscoveryRequest(latest_user_message="Find some jobs for me to apply to.", candidate_profile_slug="rebekah-love"),
            connector=connector,
            db_session=session,
            settings=make_settings(tmp_path),
        )

        assert result.status_code == 200
        assert result.body["result"]["savedCount"] == 1
        assert result.body["result"]["validationWarnings"] == [
            "First job discovery model response was truncated; compact retry succeeded."
        ]
        assert len(connector.requests) == 2
        assert connector.requests[1].metadata["retry"] == "compact_after_truncation"
        assert "Compact retry rules" in connector.requests[1].messages[0].content


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
        "skippedReasonCounts": {"Job URL was not supported by fresh search grounding/source URLs.": 3},
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
