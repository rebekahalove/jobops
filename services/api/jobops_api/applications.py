from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from jobops_api.db.models import Application, ApplicationEvent, CandidateProfile, JobRole, TargetCompany
from jobops_api.db.session import get_db_session
from jobops_api.profiles import get_candidate_profile_by_slug
from jobops_api.security import require_internal_api_key


ApplicationStatus = Literal["saved", "applied", "interviewing", "rejected", "offer", "closed", "withdrawn"]

router = APIRouter(prefix="/v1", tags=["applications"], dependencies=[Depends(require_internal_api_key)])


class ApplicationCreateRequest(BaseModel):
    candidate_profile_id: str | None = None
    candidate_profile_slug: str | None = None
    company_name: str = Field(min_length=1, max_length=240)
    job_title: str = Field(min_length=1, max_length=240)
    job_url: str | None = None
    location: str | None = Field(default=None, max_length=240)
    source: str | None = Field(default=None, max_length=120)
    date_applied: date | None = None
    status: ApplicationStatus = "saved"
    notes: str = ""
    next_follow_up_date: date | None = None


class ApplicationStatusUpdateRequest(BaseModel):
    status: ApplicationStatus


class ApplicationEventCreateRequest(BaseModel):
    event_type: str = Field(min_length=1, max_length=80)
    event_date: date
    notes: str = ""
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class ApplicationResponse(BaseModel):
    id: str
    candidate_profile_id: str
    company_name: str
    job_title: str
    job_url: str | None
    location: str | None
    source: str | None
    date_applied: date | None
    status: str
    notes: str
    next_follow_up_date: date | None
    created_at: datetime
    updated_at: datetime


class ApplicationEventResponse(BaseModel):
    id: str
    application_id: str
    event_type: str
    event_date: date
    notes: str
    metadata_json: dict[str, Any]
    created_at: datetime


@router.post("/applications", response_model=ApplicationResponse, status_code=201)
def create_application(
    request: ApplicationCreateRequest,
    session: Session = Depends(get_db_session),
) -> Application:
    candidate_profile = resolve_candidate_profile(
        session,
        candidate_profile_id=request.candidate_profile_id,
        candidate_profile_slug=request.candidate_profile_slug,
    )
    company_name = request.company_name.strip()
    job_title = request.job_title.strip()
    target_company = get_or_create_target_company(session, candidate_profile.id, company_name)
    job_role = JobRole(
        candidate_profile_id=candidate_profile.id,
        target_company_id=target_company.id,
        title=job_title,
        job_url=clean_optional_text(request.job_url),
        location=clean_optional_text(request.location),
        source=clean_optional_text(request.source),
        status=request.status,
    )
    session.add(job_role)
    session.flush()

    application = Application(
        candidate_profile_id=candidate_profile.id,
        target_company_id=target_company.id,
        job_role_id=job_role.id,
        company_name=company_name,
        job_title=job_title,
        job_url=clean_optional_text(request.job_url),
        location=clean_optional_text(request.location),
        source=clean_optional_text(request.source),
        date_applied=request.date_applied,
        status=request.status,
        notes=request.notes.strip(),
        next_follow_up_date=request.next_follow_up_date,
    )
    session.add(application)
    session.commit()
    session.refresh(application)
    return application


@router.get("/applications", response_model=list[ApplicationResponse])
def list_applications(
    candidate_profile_id: str | None = None,
    candidate_profile_slug: str | None = None,
    status: ApplicationStatus | None = None,
    session: Session = Depends(get_db_session),
) -> list[Application]:
    statement = select(Application).order_by(Application.created_at.desc())
    candidate_profile = resolve_optional_candidate_profile(
        session,
        candidate_profile_id=candidate_profile_id,
        candidate_profile_slug=candidate_profile_slug,
    )
    if candidate_profile is not None:
        statement = statement.where(Application.candidate_profile_id == candidate_profile.id)
    if status is not None:
        statement = statement.where(Application.status == status)

    return list(session.scalars(statement))


@router.patch("/applications/{application_id}/status", response_model=ApplicationResponse)
def update_application_status(
    application_id: str,
    request: ApplicationStatusUpdateRequest,
    session: Session = Depends(get_db_session),
) -> Application:
    application = session.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found.")

    application.status = request.status
    if application.job_role_id:
        job_role = session.get(JobRole, application.job_role_id)
        if job_role is not None:
            job_role.status = request.status

    session.commit()
    session.refresh(application)
    return application


@router.post("/applications/{application_id}/events", response_model=ApplicationEventResponse, status_code=201)
def add_application_event(
    application_id: str,
    request: ApplicationEventCreateRequest,
    session: Session = Depends(get_db_session),
) -> ApplicationEvent:
    application = session.get(Application, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found.")

    event = ApplicationEvent(
        application_id=application.id,
        event_type=request.event_type.strip(),
        event_date=request.event_date,
        notes=request.notes.strip(),
        metadata_json=request.metadata_json,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def resolve_candidate_profile(
    session: Session,
    *,
    candidate_profile_id: str | None,
    candidate_profile_slug: str | None,
) -> CandidateProfile:
    candidate_profile = resolve_optional_candidate_profile(
        session,
        candidate_profile_id=candidate_profile_id,
        candidate_profile_slug=candidate_profile_slug,
    )
    if candidate_profile is None:
        raise HTTPException(status_code=400, detail="candidate_profile_id or candidate_profile_slug is required.")
    return candidate_profile


def resolve_optional_candidate_profile(
    session: Session,
    *,
    candidate_profile_id: str | None,
    candidate_profile_slug: str | None,
) -> CandidateProfile | None:
    if candidate_profile_id:
        candidate_profile = session.get(CandidateProfile, candidate_profile_id)
        if candidate_profile is None:
            raise HTTPException(status_code=404, detail="Candidate profile not found.")
        return candidate_profile

    if candidate_profile_slug:
        candidate_profile = get_candidate_profile_by_slug(session, candidate_profile_slug)
        if candidate_profile is None:
            raise HTTPException(status_code=404, detail="Candidate profile not found.")
        return candidate_profile

    return None


def get_or_create_target_company(session: Session, candidate_profile_id: str, company_name: str) -> TargetCompany:
    target_company = session.scalar(
        select(TargetCompany).where(
            TargetCompany.candidate_profile_id == candidate_profile_id,
            TargetCompany.name == company_name,
        )
    )
    if target_company is not None:
        return target_company

    target_company = TargetCompany(candidate_profile_id=candidate_profile_id, name=company_name)
    session.add(target_company)
    session.flush()
    return target_company


def clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None
