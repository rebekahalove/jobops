from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, exists, func, or_, select
from sqlalchemy.orm import Session

from ...db.models import Application, CandidateSavedJob, JobListing, JobListingSource
from .models import DbJobSearchPlan, DbJobSearchQuery, JobPoolEntry
from .statuses import DISCOVERY_BLOCKING_STATUSES, HIDDEN_JOB_STATUSES, MODEL_REJECTED_STATUS


class JobListingQueryBuilder:
    def __init__(self, session: Session) -> None:
        self.session = session

    def execute_plan(self, candidate_profile_id: str, plan: DbJobSearchPlan) -> tuple[list[JobListing], tuple[tuple[str, int], ...]]:
        by_id: dict[str, JobListing] = {}
        counts: list[tuple[str, int]] = []
        for query in plan.queries:
            rows = list(
                self.session.scalars(
                    self.build_query(candidate_profile_id, plan.job_scope, query, review_task=plan.review_plan.task)
                )
                .unique()
                .all()
            )
            counts.append((query.label, len(rows)))
            for row in rows:
                by_id.setdefault(row.id, row)
            if len(by_id) >= plan.max_job_pool_size:
                break
        return list(by_id.values())[: plan.max_job_pool_size], tuple(counts)

    def build_query(
        self,
        candidate_profile_id: str,
        job_scope: str,
        query: DbJobSearchQuery,
        *,
        review_task: str = "select_new_jobs",
    ) -> Select[tuple[JobListing]]:
        effective_scope = "candidate_jobs_list" if review_task == "rank_existing_jobs" else job_scope
        statement = select(JobListing)
        if requires_source_join(query):
            statement = statement.join(JobListingSource, JobListingSource.job_listing_id == JobListing.id)

        if query.active_only:
            statement = statement.where(JobListing.is_active.is_(True), JobListing.closed_at.is_(None))
        if query.source_statuses_any:
            statement = statement.where(JobListing.source_status.in_(query.source_statuses_any))
        statement = apply_text_filters(statement, JobListing.title, query.title_terms_any, any_match=True)
        statement = apply_text_filters(statement, JobListing.title, query.title_terms_all, any_match=False)
        statement = apply_text_excludes(statement, JobListing.title, query.title_terms_exclude)
        description_expr = func.coalesce(JobListing.full_description, "") + " " + func.coalesce(JobListing.description_excerpt, "")
        statement = apply_text_filters(statement, description_expr, query.description_terms_any, any_match=True)
        statement = apply_text_filters(statement, description_expr, query.description_terms_all, any_match=False)
        statement = apply_text_excludes(statement, description_expr, query.description_terms_exclude)

        if query.company_ids_any:
            statement = statement.where(JobListing.company_id.in_(query.company_ids_any))
        statement = apply_text_filters(statement, JobListing.company_name, query.company_names_any, any_match=True)
        statement = apply_text_excludes(statement, JobListing.company_name, query.company_names_exclude)
        if query.location_target_ids_any:
            statement = statement.where(JobListing.job_location_target_id.in_(query.location_target_ids_any))
        if query.location_countries_any:
            statement = statement.where(JobListing.location_country.in_(query.location_countries_any))
        if query.location_regions_any:
            statement = statement.where(JobListing.location_region.in_(query.location_regions_any))
        if query.location_cities_any:
            statement = statement.where(JobListing.location_city.in_(query.location_cities_any))
        if query.location_metros_any:
            statement = statement.where(JobListing.location_metro.in_(query.location_metros_any))
        statement = apply_text_filters(statement, JobListing.location_display, query.location_display_terms_any, any_match=True)
        if query.remote_work_modes_any:
            statement = statement.where(JobListing.remote_work_mode.in_(query.remote_work_modes_any))
        if query.employment_types_any:
            statement = statement.where(JobListing.employment_type.in_(query.employment_types_any))
        if query.salary_currency:
            statement = statement.where(JobListing.salary_currency == query.salary_currency)
        if query.salary_min_at_least is not None:
            statement = statement.where(or_(JobListing.salary_max >= query.salary_min_at_least, JobListing.salary_min >= query.salary_min_at_least))
        if query.posting_date_after is not None:
            statement = statement.where(JobListing.posting_date >= query.posting_date_after)
        if query.source_updated_after is not None:
            statement = statement.where(JobListing.source_updated_at >= query.source_updated_after)
        if query.last_seen_after is not None:
            statement = statement.where(JobListing.last_seen_at >= query.last_seen_after)
        elif query.freshness_days:
            statement = statement.where(JobListing.last_seen_at >= datetime.now(UTC) - timedelta(days=max(1, query.freshness_days)))

        if query.source_providers_any:
            statement = statement.where(JobListingSource.source_provider.in_(query.source_providers_any))
        if query.ats_board_tokens_any:
            statement = statement.where(JobListingSource.ats_board_token.in_(query.ats_board_tokens_any))

        if effective_scope == "new_to_candidate":
            statement = statement.where(
                ~exists().where(
                    CandidateSavedJob.candidate_profile_id == candidate_profile_id,
                    CandidateSavedJob.job_listing_id == JobListing.id,
                    CandidateSavedJob.status.in_(DISCOVERY_BLOCKING_STATUSES),
                )
            )
        elif effective_scope == "candidate_jobs_list":
            statement = statement.join(CandidateSavedJob, CandidateSavedJob.job_listing_id == JobListing.id).where(
                CandidateSavedJob.candidate_profile_id == candidate_profile_id
            )
            if not query.include_model_rejected:
                statement = statement.where(CandidateSavedJob.status.not_in(HIDDEN_JOB_STATUSES))
            if review_task == "rank_existing_jobs":
                statement = statement.where(
                    CandidateSavedJob.archived_at.is_(None),
                    ~exists().where(
                        Application.candidate_profile_id == candidate_profile_id,
                        Application.saved_job_id == CandidateSavedJob.id,
                    ),
                )
        elif effective_scope == "all_accessible_jobs" and not query.include_model_rejected:
            statement = statement.where(
                ~exists().where(
                    CandidateSavedJob.candidate_profile_id == candidate_profile_id,
                    CandidateSavedJob.job_listing_id == JobListing.id,
                    CandidateSavedJob.status == MODEL_REJECTED_STATUS,
                )
            )

        if query.order_by == "posting_date_desc":
            statement = statement.order_by(JobListing.posting_date.desc().nullslast(), JobListing.last_seen_at.desc().nullslast())
        elif query.order_by == "source_updated_at_desc":
            statement = statement.order_by(JobListing.source_updated_at.desc().nullslast(), JobListing.last_seen_at.desc().nullslast())
        else:
            statement = statement.order_by(JobListing.last_seen_at.desc().nullslast(), JobListing.source_updated_at.desc().nullslast())
        return statement.limit(max(1, query.limit))


def requires_source_join(query: DbJobSearchQuery) -> bool:
    return bool(query.source_providers_any or query.ats_board_tokens_any)


def apply_text_filters(statement, column, terms: tuple[str, ...], *, any_match: bool):
    cleaned = clean_terms(terms)
    if not cleaned:
        return statement
    clauses = [column.ilike(f"%{escape_like(term)}%") for term in cleaned]
    if any_match:
        return statement.where(or_(*clauses))
    return statement.where(*clauses)


def apply_text_excludes(statement, column, terms: tuple[str, ...]):
    for term in clean_terms(terms):
        statement = statement.where(~column.ilike(f"%{escape_like(term)}%"))
    return statement


def clean_terms(terms: tuple[str, ...]) -> list[str]:
    return [" ".join(str(term).split()).strip() for term in terms if " ".join(str(term).split()).strip()]


def escape_like(value: str) -> str:
    return value.replace("%", "\\%").replace("_", "\\_")


def job_listing_to_pool_entry(job: JobListing, *, source_providers: tuple[str, ...] = ()) -> JobPoolEntry:
    return JobPoolEntry(
        job_listing_id=job.id,
        title=job.title,
        company_name=job.company_name,
        location_display=job.location_display,
        remote_work_mode=job.remote_work_mode,
        employment_type=job.employment_type,
        salary_text=job.salary_text,
        description_excerpt=job.description_excerpt,
        source_providers=source_providers,
    )
