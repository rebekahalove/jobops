from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.models import CandidateCompany, Company
from ...settings import Settings
from ..ashby_utils import parse_ashby_job_board_url
from .models import JobSyncResult
from .providers.ashby import AshbyBoardSyncTarget, AshbyJobSyncProvider, dedupe_ashby_board_sync_targets


def sync_ashby_boards(
    session: Session,
    *,
    settings: Settings,
    candidate_profile_id: str | None = None,
    board_urls: Iterable[str] | None = None,
    include_configured: bool = True,
    force: bool = False,
    freshness_hours: int = 24,
) -> list[JobSyncResult]:
    provider = AshbyJobSyncProvider()
    targets = resolve_ashby_board_sync_targets(
        session,
        settings=settings,
        candidate_profile_id=candidate_profile_id,
        board_urls=board_urls,
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


def resolve_ashby_board_sync_targets(
    session: Session,
    *,
    settings: Settings,
    candidate_profile_id: str | None = None,
    board_urls: Iterable[str] | None = None,
    include_configured: bool = True,
) -> tuple[AshbyBoardSyncTarget, ...]:
    targets: list[AshbyBoardSyncTarget] = []
    for board_url in board_urls or ():
        targets.append(AshbyBoardSyncTarget(board_url=board_url, source="explicit"))
    if include_configured:
        targets.extend(configured_ashby_board_sync_targets(settings))
    if candidate_profile_id:
        targets.extend(candidate_ashby_board_sync_targets(session, candidate_profile_id=candidate_profile_id))
    return dedupe_ashby_board_sync_targets(targets)


def configured_ashby_board_sync_targets(settings: Settings) -> tuple[AshbyBoardSyncTarget, ...]:
    return tuple(AshbyBoardSyncTarget(board_url=url, source="configured_board_url") for url in settings.ashby_board_urls)


def candidate_ashby_board_sync_targets(
    session: Session,
    *,
    candidate_profile_id: str,
) -> tuple[AshbyBoardSyncTarget, ...]:
    rows = session.execute(
        select(CandidateCompany, Company)
        .join(Company, Company.id == CandidateCompany.company_id)
        .where(CandidateCompany.candidate_profile_id == candidate_profile_id, CandidateCompany.archived_at.is_(None))
    )
    targets: list[AshbyBoardSyncTarget] = []
    for _candidate_company, company in rows:
        parsed = parse_ashby_job_board_url(company.ashby_board_url)
        if parsed:
            targets.append(
                AshbyBoardSyncTarget(
                    board_url=parsed.canonical_board_url,
                    org_slug=parsed.org_slug,
                    company_id=company.id,
                    company_name=company.name,
                    source="candidate_company_board_url",
                )
            )
    return tuple(targets)
