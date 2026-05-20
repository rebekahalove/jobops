from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Cookie, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from jobops_api.auth import (
    SESSION_COOKIE_NAME,
    accept_alpha_invite,
    auth_context_to_dict,
    clear_session_cookie,
    create_alpha_invite,
    create_session_for_username,
    require_auth_context,
    reset_user_password,
    revoke_session,
    set_session_cookie,
)
from jobops_api.db.models import CandidateProfile, Tenant, User, WorkspaceMembership
from jobops_api.db.session import get_db_session
from jobops_api.email import send_invite_email
from jobops_api.security import require_internal_api_key
from jobops_api.settings import load_settings


router = APIRouter(prefix="/v1/auth", tags=["auth"], dependencies=[Depends(require_internal_api_key)])


class InviteCreateRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    display_name: str | None = Field(default=None, max_length=200)
    workspace_slug: str | None = Field(default=None, max_length=120)
    created_by: str | None = Field(default=None, max_length=200)
    invite_base_url: str | None = Field(default=None, max_length=500)


class InviteAcceptRequest(BaseModel):
    token: str = Field(min_length=32, max_length=512)
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=12, max_length=256)
    display_name: str = Field(min_length=1, max_length=200)


class SessionCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=1, max_length=256)


class PasswordResetRequest(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


@router.get("/me")
def get_current_user(auth=Depends(require_auth_context)) -> dict[str, Any]:
    return {"ok": True, "result": auth_context_to_dict(auth)}


@router.post("/invites", status_code=201)
def create_invite(request: InviteCreateRequest, session: Session = Depends(get_db_session)) -> dict[str, Any]:
    settings = load_settings()
    created = create_alpha_invite(
        session,
        email=request.email,
        display_name=request.display_name,
        workspace_slug=request.workspace_slug,
        created_by=request.created_by,
    )
    base_url = (request.invite_base_url or settings.app_base_url or "http://localhost:3002").rstrip("/")
    invite_url = f"{base_url}/invite/{created.raw_token}"
    email_sent = send_invite_email(settings, to_email=created.invite.email, invite_url=invite_url)
    session.commit()
    return {
        "ok": True,
        "result": {
            "inviteId": created.invite.id,
            "email": created.invite.email,
            "workspaceSlug": created.invite.workspace_slug,
            "expiresAt": created.invite.expires_at.isoformat() if created.invite.expires_at else None,
            "token": created.raw_token,
            "inviteUrl": invite_url,
            "emailSent": email_sent,
        },
    }


@router.post("/invites/accept")
def accept_invite(request: InviteAcceptRequest, response: Response, session: Session = Depends(get_db_session)) -> dict[str, Any]:
    auth_context, raw_session_token = accept_alpha_invite(
        session,
        request.token,
        username=request.username,
        password=request.password,
        display_name=request.display_name,
    )
    set_session_cookie(response, raw_session_token, secure=load_settings().app_env.lower() == "prod")
    session.commit()
    return {"ok": True, "result": auth_context_to_dict(auth_context)}


@router.post("/session")
def create_session(request: SessionCreateRequest, response: Response, session: Session = Depends(get_db_session)) -> dict[str, Any]:
    auth_context, raw_session_token = create_session_for_username(session, username=request.username, password=request.password)
    set_session_cookie(response, raw_session_token, secure=load_settings().app_env.lower() == "prod")
    session.commit()
    return {"ok": True, "result": auth_context_to_dict(auth_context)}


@router.post("/password/reset")
def reset_password(request: PasswordResetRequest, response: Response, session: Session = Depends(get_db_session)) -> dict[str, Any]:
    auth_context, raw_session_token = reset_user_password(
        session,
        username=request.username,
        current_password=request.current_password,
        new_password=request.new_password,
    )
    set_session_cookie(response, raw_session_token, secure=load_settings().app_env.lower() == "prod")
    session.commit()
    return {"ok": True, "result": auth_context_to_dict(auth_context)}


@router.post("/logout")
def logout(
    response: Response,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    session: Session = Depends(get_db_session),
) -> dict[str, bool]:
    revoke_session(session, session_token)
    clear_session_cookie(response, secure=load_settings().app_env.lower() == "prod")
    session.commit()
    return {"ok": True}


@router.get("/debug/workspaces")
def inspect_workspaces(
    session: Session = Depends(get_db_session),
    auth=Depends(require_auth_context),
) -> dict[str, Any]:
    rows = session.execute(
        select(User, Tenant, CandidateProfile, WorkspaceMembership)
        .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
        .join(Tenant, Tenant.id == WorkspaceMembership.tenant_id)
        .join(CandidateProfile, CandidateProfile.tenant_id == Tenant.id, isouter=True)
        .order_by(User.email.asc(), Tenant.slug.asc())
    ).all()
    return {
        "ok": True,
        "requestedBy": auth.user.email,
        "result": [
            {
                "userEmail": user.email,
                "userId": user.id,
                "username": user.username,
                "workspaceId": tenant.id,
                "workspaceSlug": tenant.slug,
                "candidateProfileId": profile.id if profile else None,
                "candidateProfileSlug": profile.slug if profile else None,
                "role": membership.role,
            }
            for user, tenant, profile, membership in rows
        ],
    }
