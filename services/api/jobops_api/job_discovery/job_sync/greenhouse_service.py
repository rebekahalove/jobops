from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.models import CandidateCompany, Company
from ...settings import Settings
from ..greenhouse_utils import greenhouse_board_token_from_company, normalize_greenhouse_board_token
from .models import JobSyncResult
from .providers.greenhouse import GreenhouseBoardSyncTarget, GreenhouseJobSyncProvider


def sync_greenhouse_boards(
    session: Session,
    *,
    settings: Settings,
    candidate_profile_id: str | None = None,
    board_tokens: Iterable[str] | None = None,
    include_configured: bool = True,
    force: bool = False,
    freshness_hours: int = 24,
    max_detail_requests: int | None = None,
) -> list[JobSyncResult]:
    provider = GreenhouseJobSyncProvider(max_detail_requests=max_detail_requests)
    targets = resolve_greenhouse_board_sync_targets(
        session,
        settings=settings,
        candidate_profile_id=candidate_profile_id,
        board_tokens=board_tokens,
        include_configured=include_configured,
    )
    plan = provider.build_sync_plan(targets)
    return [
        provider.refresh_inventory(
            session,
            request,
            freshness_hours=freshness_hours,
            force=force,
        )
        for request in plan.requests
    ]


def resolve_greenhouse_board_sync_targets(
    session: Session,
    *,
    settings: Settings,
    candidate_profile_id: str | None = None,
    board_tokens: Iterable[str] | None = None,
    include_configured: bool = True,
) -> tuple[GreenhouseBoardSyncTarget, ...]:
    targets: list[GreenhouseBoardSyncTarget] = []
    for token in board_tokens or ():
        targets.append(GreenhouseBoardSyncTarget(board_token=token, source="explicit"))
    if include_configured:
        targets.extend(configured_greenhouse_board_sync_targets(settings))
    if candidate_profile_id:
        targets.extend(candidate_greenhouse_board_sync_targets(session, candidate_profile_id=candidate_profile_id))
    return dedupe_greenhouse_board_sync_targets(targets)


def configured_greenhouse_board_sync_targets(settings: Settings) -> tuple[GreenhouseBoardSyncTarget, ...]:
    targets: list[GreenhouseBoardSyncTarget] = [
        GreenhouseBoardSyncTarget(board_token=token, source="configured_board_token")
        for token in settings.greenhouse_board_tokens
    ]
    for company_name, token in (settings.greenhouse_company_boards or {}).items():
        targets.append(
            GreenhouseBoardSyncTarget(
                board_token=token,
                company_name=str(company_name).strip() or None,
                source="configured_company_board_token",
            )
        )
    return tuple(targets)


def candidate_greenhouse_board_sync_targets(
    session: Session,
    *,
    candidate_profile_id: str,
) -> tuple[GreenhouseBoardSyncTarget, ...]:
    rows = session.execute(
        select(CandidateCompany, Company)
        .join(Company, Company.id == CandidateCompany.company_id)
        .where(CandidateCompany.candidate_profile_id == candidate_profile_id, CandidateCompany.archived_at.is_(None))
    )
    targets: list[GreenhouseBoardSyncTarget] = []
    for _candidate_company, company in rows:
        token = greenhouse_board_token_from_company(
            {
                "name": company.name,
                "greenhouse_board_token": company.greenhouse_board_token,
                "job_listings_url": company.job_listings_url,
                "careers_url": company.careers_url,
                "source_urls": company.source_urls or [],
            }
        )
        if token:
            targets.append(
                GreenhouseBoardSyncTarget(
                    board_token=token,
                    company_id=company.id,
                    company_name=company.name,
                    source="candidate_company_board_token",
                )
            )
    return tuple(targets)


def dedupe_greenhouse_board_sync_targets(
    targets: Iterable[GreenhouseBoardSyncTarget],
) -> tuple[GreenhouseBoardSyncTarget, ...]:
    deduped: list[GreenhouseBoardSyncTarget] = []
    seen_index_by_key: dict[str, int] = {}
    for target in targets:
        token = normalize_greenhouse_board_token(target.board_token)
        key = token.casefold()
        if not token:
            continue
        normalized_target = GreenhouseBoardSyncTarget(
            board_token=token,
            company_id=target.company_id,
            company_name=target.company_name,
            source=target.source,
        )
        if key in seen_index_by_key:
            existing_index = seen_index_by_key[key]
            if greenhouse_target_metadata_score(normalized_target) > greenhouse_target_metadata_score(deduped[existing_index]):
                deduped[existing_index] = normalized_target
            continue
        seen_index_by_key[key] = len(deduped)
        deduped.append(normalized_target)
    return tuple(deduped)


def greenhouse_target_metadata_score(target: GreenhouseBoardSyncTarget) -> int:
    return int(bool(target.company_name)) + (2 * int(bool(target.company_id)))
