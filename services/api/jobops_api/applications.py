from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from jobops_api.application_materials import generate_application_material_bundle
from jobops_api.auth import AuthContext, require_auth_context
from jobops_api.company_canonicalization import ensure_candidate_company_link, normalize_company_name, upsert_canonical_company
from jobops_api.db.models import Application, ApplicationEvent, ApplicationMaterialBundle, CandidateProfile, CandidateSavedJob, Company, JobListing, JobPosting, JobRole
from jobops_api.db.session import get_db_session
from jobops_api.profiles import get_candidate_profile_by_slug
from jobops_api.security import require_internal_api_key


ApplicationStatus = Literal[
    "saved",
    "started",
    "in_progress",
    "in_process",
    "applied",
    "interviewing",
    "rejected",
    "offer",
    "closed",
    "withdrawn",
]
APPLICATION_STATUS_ALIASES = {"saved": "started", "in_progress": "in_process"}
STATUS_AUTO_ARCHIVE_ACTIONS = {
    "rejected": "status_rejected",
    "withdrawn": "status_withdrawn",
}

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
    status: ApplicationStatus = "started"
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
    archived_at: datetime | None
    archived_reason: str | None
    archived_by_action: str | None
    created_at: datetime
    updated_at: datetime
    source_provider: str | None = None
    posting_date: date | None = None
    fit_summary: str | None = None
    salary_text: str | None = None
    remote_work_mode: str | None = None
    employment_type: str | None = None
    apply_url: str | None = None
    latest_material_bundle: ApplicationMaterialBundleResponse | None = None


class ApplicationActionResponse(BaseModel):
    ok: bool = True
    application_id: str
    application_archived: bool = False
    application_restored: bool = False
    status: str
    archived_at: datetime | None = None
    message: str
    application: ApplicationResponse


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
    status = normalize_application_status(request.status)
    job_role = JobRole(
        candidate_profile_id=candidate_profile.id,
        company_id=company.id,
        title=job_title,
        job_url=clean_optional_text(request.job_url),
        location=clean_optional_text(request.location),
        source=clean_optional_text(request.source),
        status=status,
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
        status=status,
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
            selectinload(Application.saved_job).selectinload(CandidateSavedJob.job_listing).selectinload(JobListing.sources),
            selectinload(Application.material_bundles).selectinload(ApplicationMaterialBundle.items),
        )
        .where(Application.candidate_profile_id == auth.candidate_profile.id)
        .order_by(Application.created_at.desc())
    )
    if status is not None:
        normalized_status = normalize_application_status(status)
        if normalized_status == status:
            statement = statement.where(Application.status == status)
        else:
            statement = statement.where(Application.status.in_((status, normalized_status)))

    return list(session.scalars(statement))


@router.get("/applications/{application_id}", response_model=ApplicationResponse)
def get_application(
    application_id: str,
    session: Session = Depends(get_db_session),
    auth: AuthContext = Depends(require_auth_context),
) -> Application:
    return get_owned_application_or_404(session, application_id, auth.candidate_profile.id)


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
    status = normalize_application_status(request.status)
    if status in STATUS_AUTO_ARCHIVE_ACTIONS and previous_status != "applied":
        raise HTTPException(status_code=409, detail="Application must be marked applied before it can be rejected or withdrawn.")
    application.status = status
    if status == "applied":
        application.date_applied = request.date_applied or application.date_applied or date.today()
    if status in STATUS_AUTO_ARCHIVE_ACTIONS and application.date_applied is None:
        application.date_applied = request.date_applied or date.today()
    if application.job_role_id:
        job_role = session.get(JobRole, application.job_role_id)
        if job_role is not None:
            job_role.status = status

    if status == "applied" and previous_status != "applied" and application.date_applied is not None:
        session.add(
            ApplicationEvent(
                application_id=application.id,
                event_type="applied",
                event_date=application.date_applied,
                notes="",
                metadata_json={},
            )
        )
    if status in STATUS_AUTO_ARCHIVE_ACTIONS:
        session.add(
            ApplicationEvent(
                application_id=application.id,
                event_type=status,
                event_date=date.today(),
                notes=f"Application marked {status}.",
                metadata_json={"archived": True},
            )
        )
        archive_application(
            application,
            reason=f"Application marked {status}.",
            action=STATUS_AUTO_ARCHIVE_ACTIONS[status],
        )

    session.commit()
    session.refresh(application)
    return application


@router.post("/applications/{application_id}/archive", response_model=ApplicationActionResponse)
def archive_application_endpoint(
    application_id: str,
    session: Session = Depends(get_db_session),
    auth: AuthContext = Depends(require_auth_context),
) -> dict[str, Any]:
    application = get_owned_application_or_404(session, application_id, auth.candidate_profile.id)
    application_archived = archive_application(
        application,
        reason="Application archived by user.",
        action="user_archived_application",
    )
    session.commit()
    session.refresh(application)
    return application_action_response(
        application,
        application_archived=application_archived,
        message=(
            "Application archived. Saved materials and history were preserved."
            if application_archived
            else "Application was already archived. Saved materials and history are preserved."
        ),
    )


@router.post("/applications/{application_id}/restore", response_model=ApplicationActionResponse)
def restore_application_endpoint(
    application_id: str,
    session: Session = Depends(get_db_session),
    auth: AuthContext = Depends(require_auth_context),
) -> dict[str, Any]:
    application = get_owned_application_or_404(session, application_id, auth.candidate_profile.id)
    application_restored = restore_application(application)
    session.commit()
    session.refresh(application)
    return application_action_response(
        application,
        application_restored=application_restored,
        message=(
            "Application restored. Saved materials and history were preserved."
            if application_restored
            else "Application was already active. Saved materials and history are preserved."
        ),
    )


@router.post("/applications/{application_id}/reject", response_model=ApplicationActionResponse)
def mark_application_rejected(
    application_id: str,
    session: Session = Depends(get_db_session),
    auth: AuthContext = Depends(require_auth_context),
) -> dict[str, Any]:
    return mark_application_terminal_status(
        session,
        application_id=application_id,
        candidate_profile_id=auth.candidate_profile.id,
        status="rejected",
        message="Application marked rejected and archived. Saved materials and history were preserved.",
    )


@router.post("/applications/{application_id}/withdraw", response_model=ApplicationActionResponse)
def mark_application_withdrawn(
    application_id: str,
    session: Session = Depends(get_db_session),
    auth: AuthContext = Depends(require_auth_context),
) -> dict[str, Any]:
    return mark_application_terminal_status(
        session,
        application_id=application_id,
        candidate_profile_id=auth.candidate_profile.id,
        status="withdrawn",
        message="Application marked withdrawn and archived. Saved materials and history were preserved.",
    )


@router.post("/applications/{application_id}/reopen", response_model=ApplicationActionResponse)
def reopen_terminal_application(
    application_id: str,
    session: Session = Depends(get_db_session),
    auth: AuthContext = Depends(require_auth_context),
) -> dict[str, Any]:
    application = get_owned_application_or_404(session, application_id, auth.candidate_profile.id)
    if application.status not in {"rejected", "withdrawn"}:
        raise HTTPException(status_code=409, detail="Only rejected or withdrawn applications can be moved back to Applied.")

    previous_status = application.status
    application.status = "applied"
    application.date_applied = None
    application_restored = restore_application(application)
    if application.job_role_id:
        job_role = session.get(JobRole, application.job_role_id)
        if job_role is not None:
            job_role.status = "applied"
    session.add(
        ApplicationEvent(
            application_id=application.id,
            event_type="terminal_status_reset",
            event_date=date.today(),
            notes="Application moved back to Applied from rejected or withdrawn.",
            metadata_json={"previous_terminal_status": previous_status},
        )
    )
    session.commit()
    session.refresh(application)
    return application_action_response(
        application,
        application_restored=application_restored,
        message="Application moved back to Applied. Rejection or withdrawal details were cleared.",
    )


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
    saved_job = session.scalar(
        select(CandidateSavedJob)
        .options(
            selectinload(CandidateSavedJob.job),
            selectinload(CandidateSavedJob.job_listing).selectinload(JobListing.sources),
        )
        .where(CandidateSavedJob.id == request.saved_job_id)
    )
    if saved_job is None or saved_job.candidate_profile_id != candidate_profile.id:
        raise HTTPException(status_code=404, detail="Saved job not found.")

    existing_application = get_existing_application_for_saved_job(
        session,
        candidate_profile_id=candidate_profile.id,
        saved_job=saved_job,
    )
    if existing_application is not None:
        return existing_application

    job = saved_job.job
    if job is not None:
        return create_application_from_legacy_saved_job(
            session,
            candidate_profile=candidate_profile,
            saved_job=saved_job,
            job=job,
            request=request,
        )

    job_listing = saved_job.job_listing
    if job_listing is None:
        raise HTTPException(status_code=409, detail="Saved job is missing its synced job listing.")

    return create_application_from_synced_saved_job(
        session,
        candidate_profile=candidate_profile,
        saved_job=saved_job,
        job_listing=job_listing,
        request=request,
    )


def get_existing_application_for_saved_job(
    session: Session,
    *,
    candidate_profile_id: str,
    saved_job: CandidateSavedJob,
) -> Application | None:
    existing_by_saved_job = session.scalar(
        select(Application)
        .where(
            Application.candidate_profile_id == candidate_profile_id,
            Application.saved_job_id == saved_job.id,
        )
        .order_by(Application.created_at.desc())
        .limit(1)
    )
    if existing_by_saved_job is not None:
        return existing_by_saved_job
    if not saved_job.job_id:
        return None
    return session.scalar(
        select(Application)
        .where(
            Application.candidate_profile_id == candidate_profile_id,
            Application.job_id == saved_job.job_id,
        )
        .order_by(Application.created_at.desc())
        .limit(1)
    )


def create_application_from_legacy_saved_job(
    session: Session,
    *,
    candidate_profile: CandidateProfile,
    saved_job: CandidateSavedJob,
    job: JobPosting,
    request: ApplicationCreateRequest,
) -> Application:
    company = job.company if job.company is not None else get_or_create_company(session, candidate_profile.id, job.company_name)
    if job.company is not None:
        ensure_candidate_company_link(
            session,
            candidate_profile_id=candidate_profile.id,
            company=job.company,
            derivation_status="model_derived",
            review_status="new",
        )

    requested_status = request.status or "started"
    status = normalize_application_status(requested_status)
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


def create_application_from_synced_saved_job(
    session: Session,
    *,
    candidate_profile: CandidateProfile,
    saved_job: CandidateSavedJob,
    job_listing: JobListing,
    request: ApplicationCreateRequest,
) -> Application:
    company = job_listing.company if job_listing.company is not None else get_or_create_company(session, candidate_profile.id, job_listing.company_name)
    if job_listing.company is not None:
        ensure_candidate_company_link(
            session,
            candidate_profile_id=candidate_profile.id,
            company=job_listing.company,
            derivation_status="model_derived",
            review_status="new",
        )

    requested_status = request.status or "started"
    status = normalize_application_status(requested_status)
    source_provider = first_job_listing_source_provider(job_listing)
    application = Application(
        candidate_profile_id=candidate_profile.id,
        company_id=company.id if company is not None else None,
        job_id=None,
        saved_job_id=saved_job.id,
        company_name=job_listing.company_name.strip(),
        job_title=job_listing.title.strip(),
        job_url=clean_optional_text(job_listing.apply_url or job_listing.canonical_url or job_listing.source_url),
        location=clean_optional_text(job_listing.location_display or job_listing.location_raw),
        source=clean_optional_text(source_provider or "job_sync"),
        date_applied=None,
        status=status,
        notes=request.notes.strip(),
        next_follow_up_date=request.next_follow_up_date,
    )
    session.add(application)
    session.commit()
    session.refresh(application)
    return application


def first_job_listing_source_provider(job_listing: JobListing) -> str | None:
    for source in job_listing.sources:
        if source.source_provider:
            return source.source_provider
    return None


def mark_application_terminal_status(
    session: Session,
    *,
    application_id: str,
    candidate_profile_id: str,
    status: Literal["rejected", "withdrawn"],
    message: str,
) -> dict[str, Any]:
    application = get_owned_application_or_404(session, application_id, candidate_profile_id)
    if application.status != "applied":
        raise HTTPException(status_code=409, detail="Application must be marked applied before it can be rejected or withdrawn.")
    if application.date_applied is None:
        application.date_applied = date.today()
    application.status = status
    if application.job_role_id:
        job_role = session.get(JobRole, application.job_role_id)
        if job_role is not None:
            job_role.status = status
    session.add(
        ApplicationEvent(
            application_id=application.id,
            event_type=status,
            event_date=date.today(),
            notes=f"Application marked {status}.",
            metadata_json={"archived": True},
        )
    )
    application_archived = archive_application(
        application,
        reason=f"Application marked {status}.",
        action=STATUS_AUTO_ARCHIVE_ACTIONS[status],
    )
    session.commit()
    session.refresh(application)
    return application_action_response(
        application,
        application_archived=application_archived,
        message=message,
    )


def archive_application(application: Application, *, reason: str, action: str, archived_at: datetime | None = None) -> bool:
    if application.archived_at is not None:
        return False
    application.archived_at = archived_at or datetime.now(timezone.utc)
    application.archived_reason = reason
    application.archived_by_action = action
    return True


def restore_application(application: Application) -> bool:
    if application.archived_at is None:
        return False
    application.archived_at = None
    application.archived_reason = None
    application.archived_by_action = None
    return True


def normalize_application_status(status: str) -> str:
    return APPLICATION_STATUS_ALIASES.get(status, status)


def application_action_response(
    application: Application,
    *,
    application_archived: bool = False,
    application_restored: bool = False,
    message: str,
) -> dict[str, Any]:
    return {
        "ok": True,
        "application_id": application.id,
        "application_archived": application_archived,
        "application_restored": application_restored,
        "status": application.status,
        "archived_at": application.archived_at,
        "message": message,
        "application": application,
    }


def clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None
