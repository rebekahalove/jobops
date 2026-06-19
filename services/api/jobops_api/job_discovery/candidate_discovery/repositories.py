from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ...db.models import CandidateJobRejectionReason, CandidateSavedJob, JobListing, JobListingSource
from .models import JobReviewResult, RejectedJobDecision, SelectedJobDecision
from .rejection_reasons import normalize_reason_codes, resettable_field_for_reason
from .statuses import MODEL_REJECTED_STATUS, MODEL_REJECTION_RESET_STATUS


class CandidateJobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def apply_review_result(
        self,
        *,
        candidate_profile_id: str,
        job_search_run_id: str | None,
        review: JobReviewResult,
    ) -> tuple[list[CandidateSavedJob], list[CandidateSavedJob], list[CandidateSavedJob]]:
        selected = [
            self.mark_selected(
                candidate_profile_id=candidate_profile_id,
                job_search_run_id=job_search_run_id,
                decision=decision,
            )
            for decision in review.selected_jobs
        ]
        rejected = [
            self.mark_rejected(
                candidate_profile_id=candidate_profile_id,
                job_search_run_id=job_search_run_id,
                decision=decision,
            )
            for decision in review.rejected_jobs
        ]
        updated = [link for link in selected if link.created_at != link.updated_at]
        return selected, updated, rejected

    def mark_selected(
        self,
        *,
        candidate_profile_id: str,
        job_search_run_id: str | None,
        decision: SelectedJobDecision,
    ) -> CandidateSavedJob:
        now = datetime.now(UTC)
        link = self.get_or_create_link(candidate_profile_id, decision.job_listing_id)
        link.job_search_run_id = job_search_run_id
        link.status = "new"
        link.fit_summary = decision.rationale
        link.model_decision_summary = decision.rationale
        link.model_review_snapshot_json = {
            "decision": "selected",
            "matchHighlights": list(decision.match_highlights),
        }
        link.discovery_metadata = {
            **(link.discovery_metadata or {}),
            "source": "db_backed_job_discovery",
            **self.provider_source_snapshot(decision.job_listing_id),
        }
        link.last_model_reviewed_at = now
        link.model_selected_at = now
        link.model_rejected_at = None
        link.added_at = link.added_at or now
        deactivate_reasons(link, reset_reason="Selected by model.", reset_by="model")
        self.session.flush()
        return link

    def provider_source_snapshot(self, job_listing_id: str) -> dict[str, str | None]:
        source = self.session.scalar(
            select(JobListingSource)
            .where(
                JobListingSource.job_listing_id == job_listing_id,
                JobListingSource.is_active.is_(True),
                JobListingSource.last_seen_at.is_not(None),
            )
            .order_by(JobListingSource.last_seen_at.desc().nullslast(), JobListingSource.updated_at.desc().nullslast())
            .limit(1)
        )
        if source is None:
            job = self.session.get(JobListing, job_listing_id)
            return {
                "jobListingId": job_listing_id,
                "sourceProvider": None,
                "sourceUrl": job.source_url if job is not None else None,
                "fetchedAt": job.last_seen_at.isoformat() if job is not None and job.last_seen_at else None,
            }
        return {
            "jobListingId": job_listing_id,
            "sourceProvider": source.source_provider,
            "sourceUrl": source.source_url or source.apply_url or source.canonical_url,
            "sourceResultId": source.source_result_id,
            "fetchedAt": source.last_seen_at.isoformat() if source.last_seen_at else None,
        }

    def mark_rejected(
        self,
        *,
        candidate_profile_id: str,
        job_search_run_id: str | None,
        decision: RejectedJobDecision,
    ) -> CandidateSavedJob:
        now = datetime.now(UTC)
        link = self.get_or_create_link(candidate_profile_id, decision.job_listing_id)
        link.job_search_run_id = job_search_run_id
        link.status = MODEL_REJECTED_STATUS
        link.model_decision_summary = decision.explanation
        link.model_review_snapshot_json = {
            "decision": "rejected",
            "reasonCodes": list(decision.reason_codes),
            "explanation": decision.explanation,
        }
        link.last_model_reviewed_at = now
        link.model_rejected_at = now
        link.added_at = link.added_at or now
        deactivate_reasons(link, reset_reason="Superseded by latest model review.", reset_by="model")
        for reason_code in normalize_reason_codes(list(decision.reason_codes)):
            link.rejection_reasons.append(
                CandidateJobRejectionReason(
                    reason_code=reason_code,
                    affected_field=resettable_field_for_reason(reason_code),
                    explanation=decision.explanation,
                    active=True,
                )
            )
        self.session.flush()
        return link

    def get_or_create_link(self, candidate_profile_id: str, job_listing_id: str) -> CandidateSavedJob:
        link = self.session.scalar(
            select(CandidateSavedJob)
            .options(selectinload(CandidateSavedJob.rejection_reasons))
            .where(
                CandidateSavedJob.candidate_profile_id == candidate_profile_id,
                CandidateSavedJob.job_listing_id == job_listing_id,
            )
        )
        if link is not None:
            return link
        link = CandidateSavedJob(
            candidate_profile_id=candidate_profile_id,
            job_listing_id=job_listing_id,
            status="new",
            source_command="db_backed_job_discovery",
            discovery_metadata={"source": "db_backed_job_discovery"},
        )
        self.session.add(link)
        self.session.flush()
        return link


class ModelRejectionService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def reset_model_rejections(
        self,
        *,
        candidate_profile_id: str,
        reason_codes: list[str] | None = None,
        reset_reason: str = "Model rejection reset.",
        reset_by: str | None = "cli",
    ) -> int:
        normalized_reason_codes = normalize_reason_codes(reason_codes) if reason_codes else None
        statement = (
            select(CandidateSavedJob)
            .options(selectinload(CandidateSavedJob.rejection_reasons))
            .where(CandidateSavedJob.candidate_profile_id == candidate_profile_id)
        )
        links = list(self.session.scalars(statement).all())
        reset_count = 0
        now = datetime.now(UTC)
        for link in links:
            for reason in link.rejection_reasons:
                if not reason.active:
                    continue
                if normalized_reason_codes is not None and reason.reason_code not in normalized_reason_codes:
                    continue
                reason.active = False
                reason.reset_at = now
                reason.reset_reason = reset_reason
                reason.reset_by = reset_by
                reset_count += 1
            if link.status == MODEL_REJECTED_STATUS and not any(reason.active for reason in link.rejection_reasons):
                link.status = MODEL_REJECTION_RESET_STATUS
                link.model_rejected_at = None
        self.session.flush()
        return reset_count


def deactivate_reasons(link: CandidateSavedJob, *, reset_reason: str, reset_by: str) -> None:
    now = datetime.now(UTC)
    for reason in link.rejection_reasons:
        if reason.active:
            reason.active = False
            reason.reset_at = now
            reason.reset_reason = reset_reason
            reason.reset_by = reset_by


def rejection_reason_counts(links: list[CandidateSavedJob]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for link in links:
        for reason in link.rejection_reasons:
            if reason.active:
                counter[reason.reason_code] += 1
    return dict(counter)


def load_job_listings_by_id(session: Session, ids: list[str]) -> dict[str, JobListing]:
    if not ids:
        return {}
    return {job.id: job for job in session.scalars(select(JobListing).where(JobListing.id.in_(ids))).all()}
