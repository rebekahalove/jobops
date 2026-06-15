from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy.orm import Session

from ..company_canonicalization import ensure_candidate_company_link, normalize_company_name, upsert_canonical_company
from ..db.models import CandidateCompany
from .greenhouse_utils import canonical_greenhouse_jobs_api_url


@dataclass(frozen=True)
class GreenhouseSeedCompany:
    name: str
    board_token: str


GREENHOUSE_SEED_COMPANIES: tuple[GreenhouseSeedCompany, ...] = (
    GreenhouseSeedCompany("Nozomi Networks", "nozominetworks"),
    GreenhouseSeedCompany("WITHIN", "agencywithin"),
    GreenhouseSeedCompany("Mercury", "mercury"),
    GreenhouseSeedCompany("Hightouch", "hightouch"),
    GreenhouseSeedCompany("Cadence Solutions", "cadencesolutions"),
    GreenhouseSeedCompany("DoiT", "doitintl"),
    GreenhouseSeedCompany("Gradial", "gradial"),
    GreenhouseSeedCompany("AssetWatch", "assetwatch"),
    GreenhouseSeedCompany("Anthropic", "anthropic"),
)


def upsert_greenhouse_companies_for_candidate(
    session: Session,
    *,
    candidate_profile_id: str,
    companies: Iterable[GreenhouseSeedCompany] = GREENHOUSE_SEED_COMPANIES,
) -> list[CandidateCompany]:
    links: list[CandidateCompany] = []
    for seed in companies:
        jobs_api_url = canonical_greenhouse_jobs_api_url(seed.board_token)
        company = upsert_canonical_company(
            session,
            name=seed.name,
            normalized_name=normalize_company_name(seed.name),
            job_listings_url=jobs_api_url,
            source_urls=[jobs_api_url],
            source_summary="Greenhouse public job board configured for saved-company job discovery.",
            greenhouse_board_token=seed.board_token,
            data_confidence="high",
        )
        link_result = ensure_candidate_company_link(
            session,
            candidate_profile_id=candidate_profile_id,
            company=company,
            review_status="new",
            derivation_status="user_seeded",
            discovered_by="greenhouse_seed",
            personal_source_urls=[jobs_api_url],
            provider_grounding_metadata={
                "provider": "greenhouse",
                "providerType": "ats_board",
                "boardToken": seed.board_token,
                "jobListingsUrl": jobs_api_url,
            },
        )
        links.append(link_result.link)
    return links
