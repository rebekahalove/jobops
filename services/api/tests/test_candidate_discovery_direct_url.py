from __future__ import annotations

import json
from dataclasses import replace

from sqlalchemy import select
from sqlalchemy.orm import Session

import jobops_api.job_discovery.candidate_discovery.service as candidate_service_module
from jobops_api.db.models import CandidateCompany, CandidateSavedJob, Company, JobListing, JobListingSource, JobSearchRun, JobSyncRun
from jobops_api.job_discovery.candidate_discovery.direct_url.providers.greenhouse import GreenhouseDirectJobUrlProvider
from jobops_api.job_discovery.candidate_discovery.direct_url.service import DirectJobUrlDiscoveryService
from jobops_api.job_discovery.candidate_discovery.models import CandidateDiscoveryResult, DbJobSearchPlan, DbJobSearchQuery, ReviewPlan
from jobops_api.job_discovery.candidate_discovery.planner import DbJobSearchPlanner, parse_db_search_plan
from jobops_api.job_discovery.candidate_discovery.prompts import DB_JOB_SEARCH_PLAN_CRITIC_SYSTEM_PROMPT, DB_JOB_SEARCH_PLANNER_SYSTEM_PROMPT
from jobops_api.job_discovery.candidate_discovery.service import CandidateJobDiscoveryService
from jobops_api.job_discovery.job_sync.providers.greenhouse.models import GreenhouseDetailFetchResult, GreenhouseListJobsResult
from jobops_api.job_discovery.models import JobDiscoveryRequest
from jobops_api.model_connector import ModelResponse

from test_candidate_job_discovery import (
    StaticPlanner,
    create_candidate_discovery_engine,
    create_candidate_profile,
    make_settings,
)
from test_job_sync import greenhouse_list_job_raw, greenhouse_retrieve_job_raw


DIRECT_URL = "https://job-boards.greenhouse.io/vaulttec/jobs/44444"
BOARDS_URL = "https://boards.greenhouse.io/vaulttec/jobs/44444"
API_URL = "https://boards-api.greenhouse.io/v1/boards/vaulttec/jobs/44444"


def test_direct_job_url_mode_executes_direct_url_service(tmp_path, monkeypatch) -> None:
    calls: list[str] = []

    class FakeDirectService:
        def __init__(self, **kwargs):
            pass

        def run(self, request, *, candidate_profile, current_saved_companies, plan, run):
            calls.append(request.latest_user_message)
            return CandidateDiscoveryResult(
                assistant_message="direct",
                job_search_run_id=run.id,
                search_plan=plan,
                selected_candidate_jobs=(),
                updated_candidate_jobs=(),
                rejected_candidate_jobs=(),
                job_sync_results=(),
                query_counts=(),
                unique_job_pool_count=0,
                jobs_reviewed_count=0,
                added_count=0,
                updated_count=0,
                rejected_count=0,
                diagnostics={"directUrlIngestion": {"called": True}},
            )

    monkeypatch.setattr(candidate_service_module, "DirectJobUrlDiscoveryService", FakeDirectService)
    engine = create_candidate_discovery_engine()
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        service = CandidateJobDiscoveryService(
            session=session,
            settings=make_settings(tmp_path),
            planner=DirectUrlPlanner(),
        )

        result = service.run(
            JobDiscoveryRequest(latest_user_message=f"add this job {DIRECT_URL}", candidate_profile_slug=profile.slug),
            candidate_profile=profile,
            current_saved_jobs=[],
            current_saved_companies=[],
            target_context={},
            private_profile_context={},
        )

    assert calls == [f"add this job {DIRECT_URL}"]
    assert result.search_plan.mode == "direct_job_url"
    assert result.diagnostics["directUrlIngestion"]["called"] is True


def test_non_direct_plan_with_url_does_not_execute_direct_ingestion(tmp_path, monkeypatch) -> None:
    class FailingDirectService:
        def __init__(self, **kwargs):
            raise AssertionError("non-direct plans must not use direct URL ingestion")

    monkeypatch.setattr(candidate_service_module, "DirectJobUrlDiscoveryService", FailingDirectService)
    engine = create_candidate_discovery_engine()
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        service = CandidateJobDiscoveryService(
            session=session,
            settings=replace(make_settings(tmp_path), job_discovery_save_limit=1),
            planner=StaticPlanner(),
        )

        result = service.run(
            JobDiscoveryRequest(latest_user_message=f"find jobs like {DIRECT_URL}", candidate_profile_slug=profile.slug),
            candidate_profile=profile,
            current_saved_jobs=[],
            current_saved_companies=[],
            target_context={},
            private_profile_context={},
        )

    assert result.search_plan.mode == "new_job_discovery"
    assert result.added_count == 0


def test_critic_corrects_direct_url_task_planned_as_broad_search(tmp_path, monkeypatch) -> None:
    class FakeDirectService:
        def __init__(self, **kwargs):
            pass

        def run(self, request, *, candidate_profile, current_saved_companies, plan, run):
            return CandidateDiscoveryResult(
                assistant_message="direct",
                job_search_run_id=run.id,
                search_plan=plan,
                selected_candidate_jobs=(),
                updated_candidate_jobs=(),
                rejected_candidate_jobs=(),
                job_sync_results=(),
                query_counts=(),
                unique_job_pool_count=0,
                jobs_reviewed_count=0,
                added_count=0,
                updated_count=0,
                rejected_count=0,
                diagnostics={"planner": {"rejectedPlans": list(plan.rejected_plans)}},
            )

    monkeypatch.setattr(candidate_service_module, "DirectJobUrlDiscoveryService", FakeDirectService)
    engine = create_candidate_discovery_engine()
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        service = CandidateJobDiscoveryService(
            session=session,
            settings=make_settings(tmp_path),
            connector=DirectUrlCriticCorrectionConnector(),
        )
        result = service.run(
            JobDiscoveryRequest(latest_user_message=f"save this job {DIRECT_URL}", candidate_profile_slug=profile.slug),
            candidate_profile=profile,
            current_saved_jobs=[],
            current_saved_companies=[],
            target_context={},
            private_profile_context={},
        )

    assert result.search_plan.mode == "direct_job_url"
    assert result.search_plan.queries == ()
    assert result.search_plan.use_followed_company_boards is False
    assert result.search_plan.proposed_adzuna_signatures == ()
    assert result.search_plan.rejected_plans[0]["issueCode"] == "mode_mismatch_direct_url"


def test_direct_url_plan_with_no_url_fails_safely(tmp_path) -> None:
    engine = create_candidate_discovery_engine()
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        service = CandidateJobDiscoveryService(
            session=session,
            settings=make_settings(tmp_path),
            planner=DirectUrlPlanner(),
        )

        result = service.run(
            JobDiscoveryRequest(latest_user_message="add this job to my list", candidate_profile_slug=profile.slug),
            candidate_profile=profile,
            current_saved_jobs=[],
            current_saved_companies=[],
            target_context={},
            private_profile_context={},
        )
        run = session.get(JobSearchRun, result.job_search_run_id)

    assert run is not None
    assert run.status == "failed"
    assert result.added_count == 0
    assert result.diagnostics["noJobsAddedReason"] == "direct_url_missing_url"


def test_direct_url_service_uses_router_extracted_url(tmp_path) -> None:
    engine = create_candidate_discovery_engine()
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        run = JobSearchRun(candidate_profile_id=profile.id, command_text="add this job", search_mode="db_backed", status="started")
        session.add(run)
        session.flush()
        service = DirectJobUrlDiscoveryService(
            session=session,
            settings=make_settings(tmp_path),
            providers=(GreenhouseDirectJobUrlProvider(client=FakeGreenhouseClient()),),
        )
        result = service.run(
            JobDiscoveryRequest(
                latest_user_message="add this job",
                candidate_profile_slug=profile.slug,
                router_extracted={"url": DIRECT_URL, "commandRouterAction": "add_job_from_url"},
            ),
            candidate_profile=profile,
            current_saved_companies=[],
            plan=direct_plan(),
            run=run,
        )
        session.commit()
        saved = session.scalar(select(CandidateSavedJob))

    assert result.added_count == 1
    assert saved is not None
    assert saved.job_listing_id is not None
    assert result.diagnostics["directUrlIngestion"]["urls"] == [DIRECT_URL]
    assert result.diagnostics["directUrlIngestion"]["noBroadSearch"] is True
    assert result.diagnostics["planner"]["commandRouterAction"] == "add_job_from_url"


def test_parse_direct_job_url_plan_allows_empty_db_queries() -> None:
    plan = parse_db_search_plan(
        json.dumps(
            {
                "mode": "direct_job_url",
                "modeRationale": "The user supplied a specific Greenhouse job URL.",
                "syncPlan": {"useFollowedCompanyBoards": False, "proposedAdzunaSignatures": [], "existingAdzunaSignatureIdsToRefresh": []},
                "dbSearchPlan": {"queries": []},
                "reviewPlan": {"task": "select_new_jobs", "allowRejections": False},
            }
        )
    )

    assert plan.mode == "direct_job_url"
    assert plan.queries == ()
    assert plan.job_scope == "new_to_candidate"


def test_prompts_describe_direct_url_mode() -> None:
    assert "direct_job_url" in DB_JOB_SEARCH_PLANNER_SYSTEM_PROMPT
    assert "specific job URL" in DB_JOB_SEARCH_PLANNER_SYSTEM_PROMPT
    assert "mode_mismatch_direct_url" in DB_JOB_SEARCH_PLAN_CRITIC_SYSTEM_PROMPT
    assert "missing_direct_url" in DB_JOB_SEARCH_PLAN_CRITIC_SYSTEM_PROMPT


def test_greenhouse_direct_url_ingests_public_job_boards_url(tmp_path) -> None:
    result, engine = run_direct_url_service(tmp_path, DIRECT_URL, FakeGreenhouseClient())
    job_listing_id = result.diagnostics["directUrlIngestion"]["results"][0]["jobListingId"]

    with Session(engine) as session:
        listing = session.get(JobListing, job_listing_id)
        source = session.scalar(select(JobListingSource).where(JobListingSource.job_listing_id == listing.id))
        saved = session.scalar(select(CandidateSavedJob))
        company = session.scalar(select(Company))
        candidate_company = session.scalar(select(CandidateCompany))
        sync_run = session.scalar(select(JobSyncRun))

    assert result.added_count == 1
    assert listing is not None
    assert listing.company_id == company.id
    assert source is not None
    assert source.application_fields_json is not None
    assert source.raw_metadata_json["job_board_list_payload"]["id"] == 44444
    assert source.raw_metadata_json["job_board_retrieve_payload"]["questions"][1]["label"] == "Resume"
    assert source.application_fields_json["requiredQuestionLabels"] == [
        "First Name",
        "Resume",
        "Why are you interested in this role?",
        "Location",
    ]
    assert source.application_requirements_json["requiresResume"] is True
    assert source.pay_transparency_json["normalizedRanges"][0]["currency"] == "USD"
    assert saved is not None
    assert saved.job_listing_id == listing.id
    assert company.greenhouse_board_token == "vaulttec"
    assert candidate_company.company_id == company.id
    assert sync_run.sync_kind == "direct_url"
    assert sync_run.closed_count == 0
    assert sync_run.criteria_json["directUrl"] == DIRECT_URL
    assert result.diagnostics["directUrlIngestion"]["results"][0]["createdSavedJob"] is True


def test_greenhouse_direct_url_supports_boards_and_api_url_shapes(tmp_path) -> None:
    boards_result, _ = run_direct_url_service(tmp_path, BOARDS_URL, FakeGreenhouseClient())
    api_result, _ = run_direct_url_service(tmp_path, API_URL, FakeGreenhouseClient())

    assert boards_result.added_count == 1
    assert api_result.added_count == 1


def test_greenhouse_board_only_url_returns_needs_specific_job_url(tmp_path) -> None:
    result, engine = run_direct_url_service(tmp_path, "https://boards.greenhouse.io/vaulttec", FakeGreenhouseClient())

    with Session(engine) as session:
        sync_run = session.scalar(select(JobSyncRun))

    assert result.added_count == 0
    assert result.diagnostics["directUrlIngestion"]["results"][0]["error"] == "needs_specific_job_url"
    assert sync_run.status == "unsupported"


def test_greenhouse_list_response_malformed_returns_failed_diagnostic(tmp_path) -> None:
    result, _ = run_direct_url_service(
        tmp_path,
        DIRECT_URL,
        FakeGreenhouseClient(list_result=GreenhouseListJobsResult(jobs=(), provider_job_ids=(), valid=False, error="bad list")),
    )

    assert result.added_count == 0
    assert result.diagnostics["directUrlIngestion"]["failedCount"] == 1
    assert result.diagnostics["directUrlIngestion"]["results"][0]["error"] == "bad list"


def test_greenhouse_job_not_found_returns_failed_not_found(tmp_path) -> None:
    result, _ = run_direct_url_service(
        tmp_path,
        DIRECT_URL,
        FakeGreenhouseClient(list_result=GreenhouseListJobsResult(jobs=(greenhouse_list_job_raw(job_id=55555),), provider_job_ids=("55555",), valid=True)),
    )

    assert result.added_count == 0
    assert result.diagnostics["directUrlIngestion"]["results"][0]["error"] == "not_found"


def test_greenhouse_detail_failure_saves_list_level_data(tmp_path) -> None:
    result, engine = run_direct_url_service(
        tmp_path,
        DIRECT_URL,
        FakeGreenhouseClient(
            detail_result=GreenhouseDetailFetchResult(
                list_job=greenhouse_list_job_raw(),
                retrieve_error={"type": "HTTPError", "message": "503"},
            )
        ),
    )

    with Session(engine) as session:
        source = session.scalar(select(JobListingSource))

    assert result.added_count == 1
    assert source is not None
    assert source.raw_metadata_json["job_board_retrieve_error"]["message"] == "503"
    assert result.diagnostics["directUrlIngestion"]["results"][0]["diagnostics"]["detailFetchFailed"] is True


def test_direct_url_second_add_refreshes_and_archived_readd_restores(tmp_path) -> None:
    first, engine = run_direct_url_service(tmp_path, DIRECT_URL, FakeGreenhouseClient())
    with Session(engine) as session:
        saved = session.scalar(select(CandidateSavedJob))
        saved.archived_at = saved.added_at
        saved.archived_reason = "Archived"
        saved.archived_by_action = "user_archived_job"
        session.commit()
        profile = session.scalar(select(CandidateSavedJob)).candidate_profile
        run = JobSearchRun(candidate_profile_id=profile.id, command_text=f"save {DIRECT_URL}", search_mode="db_backed", status="started")
        session.add(run)
        session.flush()
        direct_service = DirectJobUrlDiscoveryService(
            session=session,
            settings=make_settings(tmp_path),
            providers=(GreenhouseDirectJobUrlProvider(client=FakeGreenhouseClient()),),
        )
        second = direct_service.run(
            JobDiscoveryRequest(latest_user_message=f"save {DIRECT_URL}", candidate_profile_slug=profile.slug),
            candidate_profile=profile,
            current_saved_companies=[],
            plan=direct_plan(),
            run=run,
        )
        session.commit()
        links = list(session.scalars(select(CandidateSavedJob)).all())
        refreshed_run = session.get(JobSearchRun, second.job_search_run_id)
        refreshed_run_status = refreshed_run.status if refreshed_run is not None else None

    assert first.added_count == 1
    assert second.added_count == 0
    assert second.updated_count == 1
    assert refreshed_run_status == "completed"
    assert second.diagnostics["noJobsAddedReason"] is None
    assert second.diagnostics["modelReview"]["modelReviewSkippedReason"] == "direct_job_url"
    assert "already on your jobs list" in second.assistant_message
    assert "refreshed" in second.assistant_message
    assert len(links) == 1
    assert links[0].archived_at is None
    assert links[0].status == "new"


def test_direct_url_refresh_preserves_existing_visible_status(tmp_path) -> None:
    _, engine = run_direct_url_service(tmp_path, DIRECT_URL, FakeGreenhouseClient())
    with Session(engine) as session:
        saved = session.scalar(select(CandidateSavedJob))
        saved.status = "favorite"
        session.commit()
        profile = session.scalar(select(CandidateSavedJob)).candidate_profile
        run = JobSearchRun(candidate_profile_id=profile.id, command_text=f"save {DIRECT_URL}", search_mode="db_backed", status="started")
        session.add(run)
        session.flush()
        result = DirectJobUrlDiscoveryService(
            session=session,
            settings=make_settings(tmp_path),
            providers=(GreenhouseDirectJobUrlProvider(client=FakeGreenhouseClient()),),
        ).run(
            JobDiscoveryRequest(latest_user_message=f"save {DIRECT_URL}", candidate_profile_slug=profile.slug),
            candidate_profile=profile,
            current_saved_companies=[],
            plan=direct_plan(),
            run=run,
        )
        session.commit()
        refreshed = session.scalar(select(CandidateSavedJob))

    assert result.updated_count == 1
    assert result.diagnostics["noJobsAddedReason"] is None
    assert refreshed.status == "favorite"


def test_greenhouse_direct_ingestion_does_not_mark_stale_jobs_closed(tmp_path) -> None:
    result, engine = run_direct_url_service(tmp_path, DIRECT_URL, FakeGreenhouseClient())

    with Session(engine) as session:
        listing = session.scalar(select(JobListing))
        sync_run = session.scalar(select(JobSyncRun))

    assert result.added_count == 1
    assert listing.is_active is True
    assert listing.closed_at is None
    assert sync_run.closed_count == 0


class DirectUrlPlanner:
    def plan(self, *args, **kwargs) -> DbJobSearchPlan:
        return direct_plan()


def direct_plan() -> DbJobSearchPlan:
    return DbJobSearchPlan(
        mode="direct_job_url",
        mode_rationale="The user supplied a specific job URL.",
        job_scope="new_to_candidate",
        queries=(),
        use_followed_company_boards=False,
        proposed_adzuna_signatures=(),
        existing_adzuna_signature_ids_to_refresh=(),
        review_plan=ReviewPlan(task="select_new_jobs", allow_rejections=False),
    )


class DirectUrlCriticCorrectionConnector:
    def generate(self, request) -> ModelResponse:
        if request.task == "candidate_db_job_plan_critique":
            return ModelResponse(
                text=json.dumps(
                    {
                        "valid": False,
                        "issueCode": "mode_mismatch_direct_url",
                        "issueMessage": "The user supplied a direct job URL.",
                        "correctedPlan": {
                            "mode": "direct_job_url",
                            "modeRationale": "The user asked to save a specific Greenhouse job URL.",
                            "syncPlan": {
                                "useFollowedCompanyBoards": False,
                                "proposedAdzunaSignatures": [],
                                "existingAdzunaSignatureIdsToRefresh": [],
                            },
                            "dbSearchPlan": {"queries": []},
                            "reviewPlan": {"task": "select_new_jobs", "allowRejections": False},
                        },
                    }
                ),
                provider="fake",
                model="fake",
            )
        return ModelResponse(
            text=json.dumps(
                {
                    "mode": "new_job_discovery",
                    "syncPlan": {
                        "useFollowedCompanyBoards": False,
                        "proposedAdzunaSignatures": [
                            {"queryText": "AI", "displayLocation": "Remote US", "queryKind": "model_planned"}
                        ],
                        "existingAdzunaSignatureIdsToRefresh": [],
                    },
                    "dbSearchPlan": {"queries": [{"label": "Broad search", "limit": 300}]},
                }
            ),
            provider="fake",
            model="fake",
        )


class FakeGreenhouseClient:
    def __init__(
        self,
        *,
        list_result: GreenhouseListJobsResult | None = None,
        detail_result: GreenhouseDetailFetchResult | None = None,
    ) -> None:
        self.list_result = list_result or GreenhouseListJobsResult(
            jobs=(greenhouse_list_job_raw(),),
            provider_job_ids=("44444",),
            valid=True,
        )
        self.detail_result = detail_result
        self.max_detail_requests = None

    def reset(self) -> None:
        pass

    def list_board_jobs(self, board_token: str) -> GreenhouseListJobsResult:
        return self.list_result

    def retrieve_job_detail(self, *, board_token: str, raw_job: object) -> GreenhouseDetailFetchResult:
        if self.detail_result is not None:
            return self.detail_result
        return GreenhouseDetailFetchResult(
            list_job=raw_job,
            retrieve_request={"url": f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/44444"},
            retrieve_job=greenhouse_retrieve_job_raw(),
        )


def run_direct_url_service(tmp_path, url: str, client: FakeGreenhouseClient):
    engine = create_candidate_discovery_engine()
    with Session(engine) as session:
        profile = create_candidate_profile(session)
        run = JobSearchRun(candidate_profile_id=profile.id, command_text=f"save {url}", search_mode="db_backed", status="started")
        session.add(run)
        session.flush()
        service = DirectJobUrlDiscoveryService(
            session=session,
            settings=make_settings(tmp_path),
            providers=(GreenhouseDirectJobUrlProvider(client=client),),
        )
        result = service.run(
            JobDiscoveryRequest(latest_user_message=f"save {url}", candidate_profile_slug=profile.slug),
            candidate_profile=profile,
            current_saved_companies=[],
            plan=direct_plan(),
            run=run,
        )
        session.commit()
    return result, engine
