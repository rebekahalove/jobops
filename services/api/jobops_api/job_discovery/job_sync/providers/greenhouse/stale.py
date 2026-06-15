from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .....db.models import JobListingSource
from ....greenhouse_utils import normalize_greenhouse_board_token
from .models import GREENHOUSE_MISSING_CLOSE_REASON


def mark_missing_greenhouse_board_jobs_closed(
    session: Session,
    *,
    board_token: str | None,
    current_provider_job_ids: Iterable[str],
    list_response_valid: bool,
) -> int:
    if not list_response_valid:
        return 0
    clean_board_token = normalize_greenhouse_board_token(board_token)
    if not clean_board_token:
        return 0
    current_ids = {str(provider_job_id).strip() for provider_job_id in current_provider_job_ids if str(provider_job_id).strip()}
    active_sources = session.scalars(
        select(JobListingSource).where(
            JobListingSource.source_provider == "greenhouse",
            JobListingSource.ats_board_token == clean_board_token,
            JobListingSource.is_active.is_(True),
        )
    ).all()
    now = datetime.now(UTC)
    closed_count = 0
    for source in active_sources:
        if source.provider_job_id and source.provider_job_id in current_ids:
            continue
        source.is_active = False
        source.closed_at = now
        source.close_reason = GREENHOUSE_MISSING_CLOSE_REASON
        listing = source.job_listing
        if not any(other_source.id != source.id and other_source.is_active for other_source in listing.sources):
            listing.is_active = False
            listing.closed_at = now
            listing.close_reason = GREENHOUSE_MISSING_CLOSE_REASON
            listing.source_status = "closed"
        closed_count += 1
    session.flush()
    return closed_count
