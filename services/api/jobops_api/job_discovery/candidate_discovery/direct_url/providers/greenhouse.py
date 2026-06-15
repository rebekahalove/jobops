from __future__ import annotations

from dataclasses import replace
from typing import Any

from ....greenhouse_utils import parse_greenhouse_url
from ....provider_utils import clean_text_value
from ....job_sync.models import JobSyncRequest, JobSyncResult
from ....job_sync.providers.greenhouse.client import GreenhouseJobBoardClient
from ....job_sync.providers.greenhouse.mapper import merge_greenhouse_job_payloads, normalize_greenhouse_job_record
from ....job_sync.providers.greenhouse.models import GreenhouseDetailFetchResult
from ....job_sync.service import record_job_sync_run, upsert_job_listing_from_provider_record
from ..models import DirectJobUrlIngestionContext, DirectJobUrlIngestionResult
from ..repository import GreenhouseDirectUrlCompanyResolver


class GreenhouseDirectJobUrlProvider:
    provider_name = "greenhouse"

    def __init__(
        self,
        *,
        client: GreenhouseJobBoardClient | None = None,
        company_resolver_class: type[GreenhouseDirectUrlCompanyResolver] = GreenhouseDirectUrlCompanyResolver,
    ) -> None:
        self.client = client or GreenhouseJobBoardClient()
        self.company_resolver_class = company_resolver_class

    def can_handle(self, url: str) -> bool:
        return parse_greenhouse_url(url) is not None

    def ingest(self, url: str, context: DirectJobUrlIngestionContext) -> DirectJobUrlIngestionResult:
        parsed = parse_greenhouse_url(url)
        if parsed is None:
            return DirectJobUrlIngestionResult(
                status="unsupported",
                provider=self.provider_name,
                url=url,
                diagnostics={"unsupportedReason": "unsupported_url"},
                error="unsupported_url",
            )

        diagnostics: dict[str, Any] = {
            "provider": self.provider_name,
            "boardToken": parsed.board_token,
            "providerJobId": parsed.job_id,
            "directUrl": url,
            "parsedUrlKind": "api" if "boards-api.greenhouse.io" in url.casefold() else "public",
            "listFetchAttempted": False,
            "listFetchSucceeded": False,
            "detailFetchAttempted": False,
            "detailFetchSucceeded": False,
            "detailFetchFailed": False,
            "applicationFieldsIncluded": False,
        }

        request = self.build_request(
            direct_url=url,
            board_token=parsed.board_token,
            provider_job_id=parsed.job_id,
            company_id=None,
            company_name=None,
            diagnostics=diagnostics,
        )

        if not parsed.job_id:
            sync_result = JobSyncResult(
                request=request,
                status="unsupported",
                diagnostics_json={**diagnostics, "unsupportedReason": "needs_specific_job_url"},
            )
            record_job_sync_run(context.session, sync_result)
            return DirectJobUrlIngestionResult(
                status="unsupported",
                provider=self.provider_name,
                url=url,
                sync_result=sync_result,
                diagnostics=sync_result.diagnostics_json,
                error="needs_specific_job_url",
            )

        company_resolution = self.company_resolver_class(context.session).resolve(
            candidate_profile_id=context.candidate_profile.id,
            board_token=parsed.board_token,
            direct_url=url,
        )
        request = replace(
            request,
            company_id=company_resolution.company.id,
            company_name=company_resolution.company.name,
        )
        diagnostics.update(
            {
                "companyId": company_resolution.company.id,
                "candidateCompanyId": company_resolution.candidate_company.id,
            }
        )

        try:
            diagnostics["listFetchAttempted"] = True
            self.client.reset()
            list_result = self.client.list_board_jobs(parsed.board_token)
        except Exception as error:
            sync_result = JobSyncResult(
                request=request,
                status="failed",
                error=str(error),
                diagnostics_json={**diagnostics, "listFetchError": safe_error(error)},
            )
            record_job_sync_run(context.session, sync_result)
            return DirectJobUrlIngestionResult(
                status="failed",
                provider=self.provider_name,
                url=url,
                sync_result=sync_result,
                company_id=company_resolution.company.id,
                candidate_company_id=company_resolution.candidate_company.id,
                diagnostics=sync_result.diagnostics_json,
                error=str(error),
            )

        if not list_result.valid:
            sync_result = JobSyncResult(
                request=request,
                status="failed",
                error=list_result.error or "Greenhouse list-jobs response was malformed.",
                diagnostics_json={
                    **diagnostics,
                    "listFetchSucceeded": False,
                    "listResponseValid": False,
                    "listFetchError": list_result.error,
                },
            )
            record_job_sync_run(context.session, sync_result)
            return DirectJobUrlIngestionResult(
                status="failed",
                provider=self.provider_name,
                url=url,
                sync_result=sync_result,
                company_id=company_resolution.company.id,
                candidate_company_id=company_resolution.candidate_company.id,
                diagnostics=sync_result.diagnostics_json,
                error=sync_result.error,
            )

        diagnostics["listFetchSucceeded"] = True
        raw_job = find_greenhouse_job(list_result.jobs, provider_job_id=parsed.job_id, direct_url=url)
        if raw_job is None:
            sync_result = JobSyncResult(
                request=request,
                status="failed",
                raw_result_count=len(list_result.jobs),
                error="not_found",
                diagnostics_json={**diagnostics, "notFound": True, "listJobsRawCount": len(list_result.jobs)},
            )
            record_job_sync_run(context.session, sync_result)
            return DirectJobUrlIngestionResult(
                status="failed",
                provider=self.provider_name,
                url=url,
                sync_result=sync_result,
                company_id=company_resolution.company.id,
                candidate_company_id=company_resolution.candidate_company.id,
                diagnostics=sync_result.diagnostics_json,
                error="not_found",
            )

        detail_result = self.client.retrieve_job_detail(board_token=parsed.board_token, raw_job=raw_job)
        diagnostics["detailFetchAttempted"] = True
        if isinstance(detail_result, GreenhouseDetailFetchResult):
            diagnostics["detailFetchSucceeded"] = detail_result.retrieve_job is not None
            diagnostics["detailFetchFailed"] = detail_result.retrieve_error is not None
            raw = merge_greenhouse_job_payloads(detail_result)
        else:
            raw = detail_result

        normalized = normalize_greenhouse_job_record(raw, request, session=context.session)
        if normalized is None:
            sync_result = JobSyncResult(
                request=request,
                status="failed",
                raw_result_count=1,
                failed_normalization_count=1,
                error="failed_normalization",
                diagnostics_json=diagnostics,
            )
            record_job_sync_run(context.session, sync_result)
            return DirectJobUrlIngestionResult(
                status="failed",
                provider=self.provider_name,
                url=url,
                sync_result=sync_result,
                company_id=company_resolution.company.id,
                candidate_company_id=company_resolution.candidate_company.id,
                diagnostics=sync_result.diagnostics_json,
                error="failed_normalization",
            )

        listing, source = normalized
        upsert = upsert_job_listing_from_provider_record(context.session, listing=listing, source=source)
        diagnostics.update(
            {
                "applicationFieldsIncluded": bool(source.application_fields_json),
                "jobListingId": upsert.job_listing_id,
                "jobListingSourceId": upsert.job_listing_source_id,
                "createdListing": upsert.created,
                "updatedListing": upsert.updated,
                "listJobsRawCount": len(list_result.jobs),
            }
        )
        sync_result = JobSyncResult(
            request=request,
            raw_result_count=1,
            normalized_count=1,
            created_count=int(upsert.created),
            updated_count=int(upsert.updated),
            closed_count=0,
            diagnostics_json=diagnostics,
        )
        record_job_sync_run(context.session, sync_result)
        return DirectJobUrlIngestionResult(
            status="added" if upsert.created else "refreshed",
            provider=self.provider_name,
            url=url,
            job_listing_id=upsert.job_listing_id,
            job_listing_source_id=upsert.job_listing_source_id,
            company_id=company_resolution.company.id,
            candidate_company_id=company_resolution.candidate_company.id,
            created_listing=upsert.created,
            updated_listing=upsert.updated,
            sync_result=sync_result,
            diagnostics=diagnostics,
        )

    def build_request(
        self,
        *,
        direct_url: str,
        board_token: str,
        provider_job_id: str | None,
        company_id: str | None,
        company_name: str | None,
        diagnostics: dict[str, Any],
    ) -> JobSyncRequest:
        return JobSyncRequest(
            sync_key=f"greenhouse:direct-url:{board_token}:{provider_job_id or 'missing-job-id'}",
            provider_name="greenhouse",
            provider_type="ats_board",
            sync_kind="direct_url",
            company_id=company_id,
            company_name=company_name,
            ats_provider="greenhouse",
            ats_board_token=board_token,
            query_text=None,
            criteria_json={
                "directUrl": direct_url,
                "boardToken": board_token,
                "providerJobId": provider_job_id,
                "listJobsContentParam": True,
                "retrieveJobQuestions": True,
                "retrieveJobPayTransparency": True,
                "source": "direct_job_url",
                "parsedUrlKind": diagnostics.get("parsedUrlKind"),
            },
        )


def find_greenhouse_job(jobs: tuple[object, ...], *, provider_job_id: str, direct_url: str) -> dict[str, object] | None:
    for raw in jobs:
        if not isinstance(raw, dict):
            continue
        raw_id = clean_text_value(raw.get("id"))
        if raw_id == provider_job_id:
            return raw
        absolute_url = clean_text_value(raw.get("absolute_url"))
        parsed_absolute = parse_greenhouse_url(absolute_url)
        if parsed_absolute is not None and parsed_absolute.job_id == provider_job_id:
            return raw
        if absolute_url and absolute_url.rstrip("/") == direct_url.rstrip("/"):
            return raw
    return None


def safe_error(error: BaseException) -> dict[str, str]:
    return {"type": type(error).__name__, "message": str(error)}
