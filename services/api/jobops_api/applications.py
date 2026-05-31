from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from jobops_api.application_materials import generate_application_material_bundle
from jobops_api.auth import AuthContext, require_auth_context
from jobops_api.company_canonicalization import ensure_candidate_company_link, normalize_company_name, upsert_canonical_company
from jobops_api.db.models import Application, ApplicationEvent, ApplicationMaterialBundle, CandidateProfile, CandidateSavedJob, Company, JobPageExtraction, JobPosting, JobRole
from jobops_api.db.session import get_db_session
from jobops_api.job_page_extraction import JobPageExtractionError, extract_job_page_requirements, get_latest_job_page_extraction_for_application
from jobops_api.profiles import get_candidate_profile_by_slug
from jobops_api.security import require_internal_api_key


ApplicationStatus = Literal["saved", "in_progress", "applied", "interviewing", "rejected", "offer", "closed", "withdrawn"]
ACTIVE_APPLICATION_STATUSES = ("saved", "in_progress", "applied", "interviewing", "offer")

router = APIRouter(prefix="/v1", tags=["applications"], dependencies=[Depends(require_internal_api_key)])


class ApplicationCreateRequest(BaseModel):
    candidate_profile_id: str | None = None
    candidate_profile_slug: str | None = None
    saved_job_id: str | None = None
    company_name: str | None = Field(default=None, max_length=240)
    job_title: str | None = Field(default=None, max_length=240)
    job_url: str | None = None
    location: str | None = Field(default=None, max_length=240)
    source: str | None = Field(default=None, max_length=120)
    date_applied: date | None = None
    status: ApplicationStatus = "saved"
    notes: str = ""
    next_follow_up_date: date | None = None


class ApplicationStatusUpdateRequest(BaseModel):
    status: ApplicationStatus
    date_applied: date | None = None


class ApplicationEventCreateRequest(BaseModel):
    event_type: str = Field(min_length=1, max_length=80)
    event_date: date
    notes: str = ""
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class ApplicationMaterialItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    bundle_id: str
    material_type: str
    title: str
    content: str
    content_format: str
    sort_order: int
    created_at: datetime
    updated_at: datetime


class ApplicationMaterialBundleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    application_id: str
    candidate_profile_id: str
    status: str
    model_provider: str | None
    model_name: str | None
    created_at: datetime
    updated_at: datetime
    items: list[ApplicationMaterialItemResponse] = Field(default_factory=list)


class ApplicationMaterialsGenerateResponse(BaseModel):
    ok: bool
    assistantMessage: str | None = None
    warnings: list[str] = Field(default_factory=list)
    bundle: ApplicationMaterialBundleResponse
    contextManifest: dict[str, Any] | None = None


class JobPageExtractionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_id: str
    extraction_status: str
    platform: str
    confidence: str
    fetched_at: datetime
    source_url: str
    final_url: str | None
    http_status: int | None = None
    page_title: str | None = None
    required_materials: list[dict[str, Any]] = Field(default_factory=list)
    optional_materials: list[dict[str, Any]] = Field(default_factory=list)
    application_fields: list[dict[str, Any]] = Field(default_factory=list)
    screening_questions: list[dict[str, Any]] = Field(default_factory=list)
    detected_requirements: dict[str, Any] = Field(default_factory=dict)
    extraction_summary: str | None = None
    warnings: list[str] = Field(default_factory=list)
    error_message: str | None = None


class ApplicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    candidate_profile_id: str
    job_id: str | None
    saved_job_id: str | None
    company_id: str | None
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
    source_provider: str | None = None
    posting_date: date | None = None
    fit_summary: str | None = None
    salary_text: str | None = None
    remote_work_mode: str | None = None
    employment_type: str | None = None
    latest_material_bundle: ApplicationMaterialBundleResponse | None = None
    latest_job_page_extraction: JobPageExtractionResponse | None = None


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
    auth: AuthContext = Depends(require_auth_context),
) -> Application:
    candidate_profile = auth.candidate_profile
    if request.saved_job_id:
        return create_application_from_saved_job(session, candidate_profile=candidate_profile, request=request)

    if request.company_name is None or request.job_title is None:
        raise HTTPException(status_code=400, detail="company_name and job_title are required unless saved_job_id is provided.")

    company_name = request.company_name.strip()
    job_title = request.job_title.strip()
    if not company_name or not job_title:
        raise HTTPException(status_code=400, detail="company_name and job_title are required unless saved_job_id is provided.")

    company = get_or_create_company(session, candidate_profile.id, company_name)
    job_role = JobRole(
        candidate_profile_id=candidate_profile.id,
        company_id=company.id,
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
        company_id=company.id,
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
    auth: AuthContext = Depends(require_auth_context),
) -> list[Application]:
    statement = (
        select(Application)
        .options(
            selectinload(Application.job),
            selectinload(Application.job).selectinload(JobPosting.page_extractions),
            selectinload(Application.saved_job),
            selectinload(Application.material_bundles).selectinload(ApplicationMaterialBundle.items),
        )
        .where(Application.candidate_profile_id == auth.candidate_profile.id)
        .order_by(Application.created_at.desc())
    )
    if status is not None:
        statement = statement.where(Application.status == status)

    return list(session.scalars(statement))


@router.get("/applications/{application_id}/materials", response_model=list[ApplicationMaterialBundleResponse])
def list_application_materials(
    application_id: str,
    session: Session = Depends(get_db_session),
    auth: AuthContext = Depends(require_auth_context),
) -> list[ApplicationMaterialBundle]:
    application = get_owned_application_or_404(session, application_id, auth.candidate_profile.id)
    statement = (
        select(ApplicationMaterialBundle)
        .options(selectinload(ApplicationMaterialBundle.items))
        .where(ApplicationMaterialBundle.application_id == application.id)
        .order_by(ApplicationMaterialBundle.created_at.desc())
    )
    return list(session.scalars(statement))


@router.post("/applications/{application_id}/materials/generate", response_model=ApplicationMaterialsGenerateResponse, status_code=201)
def generate_application_materials(
    application_id: str,
    session: Session = Depends(get_db_session),
    auth: AuthContext = Depends(require_auth_context),
) -> Any:
    application = get_owned_application_or_404(session, application_id, auth.candidate_profile.id)
    result = generate_application_material_bundle(session=session, application=application)
    if result.bundle is None:
        return JSONResponse(content=result.body, status_code=result.status_code)
    return result.body


@router.get("/applications/{application_id}/requirements", response_model=JobPageExtractionResponse | None)
def get_application_requirements(
    application_id: str,
    session: Session = Depends(get_db_session),
    auth: AuthContext = Depends(require_auth_context),
) -> JobPageExtraction | None:
    application = get_owned_application_or_404(session, application_id, auth.candidate_profile.id)
    return get_latest_job_page_extraction_for_application(session, application)


@router.post("/applications/{application_id}/requirements/extract", response_model=JobPageExtractionResponse, status_code=201)
def extract_application_requirements(
    application_id: str,
    session: Session = Depends(get_db_session),
    auth: AuthContext = Depends(require_auth_context),
) -> JobPageExtraction | JSONResponse:
    application = get_owned_application_or_404(session, application_id, auth.candidate_profile.id)
    try:
        return extract_job_page_requirements(session=session, application=application)
    except JobPageExtractionError as error:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "error": str(error),
                "code": "job_page_extraction_unavailable",
            },
        )


@router.patch("/applications/{application_id}/status", response_model=ApplicationResponse)
def update_application_status(
    application_id: str,
    request: ApplicationStatusUpdateRequest,
    session: Session = Depends(get_db_session),
    auth: AuthContext = Depends(require_auth_context),
) -> Application:
    application = session.get(Application, application_id)
    if application is None or application.candidate_profile_id != auth.candidate_profile.id:
        raise HTTPException(status_code=404, detail="Application not found.")

    previous_status = application.status
    application.status = request.status
    if request.status == "applied":
        application.date_applied = request.date_applied or application.date_applied or date.today()
    if application.job_role_id:
        job_role = session.get(JobRole, application.job_role_id)
        if job_role is not None:
            job_role.status = request.status

    if request.status == "applied" and previous_status != "applied" and application.date_applied is not None:
        session.add(
            ApplicationEvent(
                application_id=application.id,
                event_type="applied",
                event_date=application.date_applied,
                notes="",
                metadata_json={},
            )
        )

    session.commit()
    session.refresh(application)
    return application


@router.post("/applications/{application_id}/events", response_model=ApplicationEventResponse, status_code=201)
def add_application_event(
    application_id: str,
    request: ApplicationEventCreateRequest,
    session: Session = Depends(get_db_session),
    auth: AuthContext = Depends(require_auth_context),
) -> ApplicationEvent:
    application = session.get(Application, application_id)
    if application is None or application.candidate_profile_id != auth.candidate_profile.id:
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


def get_owned_application_or_404(session: Session, application_id: str, candidate_profile_id: str) -> Application:
    application = session.scalar(
        select(Application)
        .options(
            selectinload(Application.job),
            selectinload(Application.job).selectinload(JobPosting.page_extractions),
            selectinload(Application.saved_job),
            selectinload(Application.candidate_profile),
            selectinload(Application.material_bundles).selectinload(ApplicationMaterialBundle.items),
        )
        .where(Application.id == application_id)
    )
    if application is None or application.candidate_profile_id != candidate_profile_id:
        raise HTTPException(status_code=404, detail="Application not found.")
    return application


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


def get_or_create_company(session: Session, candidate_profile_id: str, company_name: str) -> Company:
    company = upsert_canonical_company(
        session,
        name=company_name,
        normalized_name=normalize_company_name(company_name),
    )
    ensure_candidate_company_link(
        session,
        candidate_profile_id=candidate_profile_id,
        company=company,
        derivation_status="user_entered",
        review_status="reviewed",
    )
    return company


def create_application_from_saved_job(
    session: Session,
    *,
    candidate_profile: CandidateProfile,
    request: ApplicationCreateRequest,
) -> Application:
    saved_job = session.get(CandidateSavedJob, request.saved_job_id)
    if saved_job is None or saved_job.candidate_profile_id != candidate_profile.id:
        raise HTTPException(status_code=404, detail="Saved job not found.")

    job = session.get(JobPosting, saved_job.job_id)
    if job is None:
        raise HTTPException(status_code=409, detail="Saved job is missing its canonical job posting.")

    existing_application = session.scalar(
        select(Application)
        .where(
            Application.candidate_profile_id == candidate_profile.id,
            Application.job_id == job.id,
            Application.status.in_(ACTIVE_APPLICATION_STATUSES),
        )
        .order_by(Application.created_at.desc())
        .limit(1)
    )
    if existing_application is not None:
        return existing_application

    company = job.company if job.company is not None else get_or_create_company(session, candidate_profile.id, job.company_name)
    if job.company is not None:
        ensure_candidate_company_link(
            session,
            candidate_profile_id=candidate_profile.id,
            company=job.company,
            derivation_status="model_derived",
            review_status="new",
        )

    requested_status = request.status or "in_progress"
    status = "in_progress" if requested_status == "saved" else requested_status
    application = Application(
        candidate_profile_id=candidate_profile.id,
        company_id=company.id if company is not None else None,
        job_id=job.id,
        saved_job_id=saved_job.id,
        company_name=job.company_name.strip(),
        job_title=job.title.strip(),
        job_url=clean_optional_text(job.job_url),
        location=clean_optional_text(job.location),
        source=clean_optional_text(job.source or job.source_provider),
        date_applied=None,
        status=status,
        notes=request.notes.strip(),
        next_follow_up_date=request.next_follow_up_date,
    )
    session.add(application)
    session.commit()
    session.refresh(application)
    return application


def clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None
