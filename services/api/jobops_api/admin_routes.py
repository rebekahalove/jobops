from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jobops_api.auth import (
    AuthContext,
    USER_TYPE_ADMIN,
    USER_TYPE_USER,
    accept_alpha_invitation,
    auth_context_to_dict,
    create_or_rotate_alpha_invitation,
    create_password_reset_token_for_user,
    mark_matching_alpha_request_invited,
    normalize_email,
    normalize_user_type,
    now_utc,
    require_admin_context,
    revoke_user_sessions,
    set_session_cookie,
)
from jobops_api.db.models import AlphaAccessRequest, AlphaInvitation, User
from jobops_api.db.session import get_db_session
from jobops_api.email import send_invite_email, send_password_reset_email
from jobops_api.security import require_internal_api_key
from jobops_api.settings import load_settings


admin_router = APIRouter(
    prefix="/v1/admin",
    tags=["admin"],
    dependencies=[Depends(require_internal_api_key)],
)
invitation_router = APIRouter(
    prefix="/v1/invitations",
    tags=["invitations"],
    dependencies=[Depends(require_internal_api_key)],
)


class RoleUpdateRequest(BaseModel):
    user_type: str = Field(min_length=4, max_length=40)


class InviteCreateRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    invite_base_url: str | None = Field(default=None, max_length=500)


class AlphaRequestInviteRequest(BaseModel):
    invite_base_url: str | None = Field(default=None, max_length=500)


class InviteAcceptRequest(BaseModel):
    token: str = Field(min_length=32, max_length=512)
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=12, max_length=256)
    display_name: str = Field(min_length=1, max_length=200)


@admin_router.get("/users")
def list_users(session: Session = Depends(get_db_session), admin: AuthContext = Depends(require_admin_context)) -> dict[str, Any]:
    users = list(session.scalars(select(User).order_by(User.created_at.asc(), User.email.asc())))
    return {
        "ok": True,
        "requestedBy": admin.user.email,
        "result": {
            "users": [user_to_admin_dict(user) for user in users],
            "adminCount": active_admin_count(session),
        },
    }


@admin_router.patch("/users/{user_id}/role")
def update_user_role(
    user_id: str,
    request: RoleUpdateRequest,
    session: Session = Depends(get_db_session),
    admin: AuthContext = Depends(require_admin_context),
) -> dict[str, Any]:
    target = get_user_or_404(session, user_id)
    next_type = normalize_user_type(request.user_type)
    if target.id == admin.user.id and next_type != USER_TYPE_ADMIN:
        raise HTTPException(status_code=400, detail="Admins cannot demote their own account.")
    if target.user_type == USER_TYPE_ADMIN and next_type != USER_TYPE_ADMIN:
        ensure_not_last_admin(session, target.id)
    target.user_type = next_type
    session.commit()
    return {"ok": True, "result": {"user": user_to_admin_dict(target)}}


@admin_router.delete("/users/{user_id}")
def delete_user(
    user_id: str,
    session: Session = Depends(get_db_session),
    admin: AuthContext = Depends(require_admin_context),
) -> dict[str, Any]:
    target = get_user_or_404(session, user_id)
    if target.id == admin.user.id:
        raise HTTPException(status_code=400, detail="Admins cannot delete their own account from Manage Users.")
    if target.user_type == USER_TYPE_ADMIN:
        ensure_not_last_admin(session, target.id)

    revoke_user_sessions(session, target.id)
    target.email = f"deleted-{target.id}@deleted.jobops.local"
    target.username = f"deleted-{target.id[:28]}"
    target.display_name = "Deleted JobOps alpha user"
    target.password_hash = None
    target.status = "deleted"
    target.user_type = USER_TYPE_USER
    target.password_reset_required = False
    target.password_expires_at = None
    session.commit()
    return {"ok": True, "result": {"deleted": True, "user": user_to_admin_dict(target)}}


@admin_router.post("/users/{user_id}/expire-password")
def expire_user_password(
    user_id: str,
    session: Session = Depends(get_db_session),
    admin: AuthContext = Depends(require_admin_context),
) -> dict[str, Any]:
    target = get_user_or_404(session, user_id)
    if target.status != "active":
        raise HTTPException(status_code=400, detail="Only active users can receive password reset links.")
    target.password_reset_required = True
    target.password_expires_at = now_utc()
    revoke_user_sessions(session, target.id)
    created = create_password_reset_token_for_user(session, user=target)
    settings = load_settings()
    reset_url = f"{(settings.app_base_url or 'http://localhost:3002').rstrip('/')}/reset-password?token={created.raw_token}"
    email_sent = send_password_reset_email(settings, to_email=target.email, reset_url=reset_url)
    session.commit()
    return {"ok": True, "result": {"user": user_to_admin_dict(target), "emailSent": email_sent}}


@admin_router.get("/alpha-requests")
def list_pending_alpha_requests(
    session: Session = Depends(get_db_session),
    admin: AuthContext = Depends(require_admin_context),
) -> dict[str, Any]:
    requests = list(
        session.scalars(
            select(AlphaAccessRequest)
            .where(AlphaAccessRequest.status == "pending")
            .order_by(AlphaAccessRequest.created_at.asc())
        )
    )
    return {
        "ok": True,
        "requestedBy": admin.user.email,
        "result": {"requests": [alpha_request_to_dict(item) for item in requests]},
    }


@admin_router.post("/alpha-requests/{request_id}/invite", status_code=201)
def invite_alpha_request(
    request_id: str,
    request: AlphaRequestInviteRequest | None = None,
    session: Session = Depends(get_db_session),
    admin: AuthContext = Depends(require_admin_context),
) -> dict[str, Any]:
    access_request = session.get(AlphaAccessRequest, request_id)
    if access_request is None:
        raise HTTPException(status_code=404, detail="Alpha access request not found.")
    created = create_and_send_invitation(
        session,
        email=access_request.email,
        invited_by_user_id=admin.user.id,
        invite_base_url=request.invite_base_url if request else None,
    )
    access_request.status = "invited"
    access_request.invited_at = now_utc()
    access_request.invitation_id = created["invitation"].id
    session.commit()
    return {
        "ok": True,
        "result": {
            "request": alpha_request_to_dict(access_request),
            "invitation": alpha_invitation_to_dict(created["invitation"]),
            "emailSent": created["email_sent"],
            "rotatedExisting": created["rotated_existing"],
        },
    }


@admin_router.post("/invitations", status_code=201)
def create_invitation(
    request: InviteCreateRequest,
    session: Session = Depends(get_db_session),
    admin: AuthContext = Depends(require_admin_context),
) -> dict[str, Any]:
    created = create_and_send_invitation(
        session,
        email=request.email,
        invited_by_user_id=admin.user.id,
        invite_base_url=request.invite_base_url,
    )
    access_request = mark_matching_alpha_request_invited(
        session,
        email=created["invitation"].email,
        invitation_id=created["invitation"].id,
    )
    session.commit()
    return {
        "ok": True,
        "result": {
            "invitation": alpha_invitation_to_dict(created["invitation"]),
            "matchedRequest": alpha_request_to_dict(access_request) if access_request else None,
            "emailSent": created["email_sent"],
            "rotatedExisting": created["rotated_existing"],
        },
    }


@invitation_router.post("/accept")
def accept_invitation(request: InviteAcceptRequest, response: Response, session: Session = Depends(get_db_session)) -> dict[str, Any]:
    auth_context, raw_session_token = accept_alpha_invitation(
        session,
        request.token,
        username=request.username,
        password=request.password,
        display_name=request.display_name,
    )
    set_session_cookie(response, raw_session_token, secure=load_settings().app_env.lower() == "prod")
    session.commit()
    return {"ok": True, "result": auth_context_to_dict(auth_context)}


def create_and_send_invitation(
    session: Session,
    *,
    email: str,
    invited_by_user_id: str,
    invite_base_url: str | None,
) -> dict[str, Any]:
    created = create_or_rotate_alpha_invitation(session, email=email, invited_by_user_id=invited_by_user_id)
    settings = load_settings()
    base_url = (invite_base_url or settings.app_base_url or "http://localhost:3002").rstrip("/")
    invite_url = f"{base_url}/accept-invite?token={created.raw_token}"
    email_sent = send_invite_email(settings, to_email=created.invitation.email, invite_url=invite_url)
    return {"invitation": created.invitation, "email_sent": email_sent, "rotated_existing": created.rotated_existing}


def get_user_or_404(session: Session, user_id: str) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return user


def active_admin_count(session: Session) -> int:
    return int(
        session.scalar(
            select(func.count()).select_from(User).where(User.status == "active", User.user_type == USER_TYPE_ADMIN)
        )
        or 0
    )


def ensure_not_last_admin(session: Session, target_user_id: str) -> None:
    remaining_admins = int(
        session.scalar(
            select(func.count()).select_from(User).where(
                User.status == "active",
                User.user_type == USER_TYPE_ADMIN,
                User.id != target_user_id,
            )
        )
        or 0
    )
    if remaining_admins < 1:
        raise HTTPException(status_code=400, detail="Cannot remove the last active admin.")


def user_to_admin_dict(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "displayName": user.display_name,
        "userType": user.user_type,
        "status": user.status,
        "createdAt": user.created_at.isoformat() if user.created_at else None,
        "passwordResetRequired": user.password_reset_required,
        "passwordExpiresAt": user.password_expires_at.isoformat() if user.password_expires_at else None,
        "hasPassword": bool(user.password_hash),
    }


def alpha_request_to_dict(access_request: AlphaAccessRequest) -> dict[str, Any]:
    return {
        "id": access_request.id,
        "name": access_request.name,
        "email": access_request.email,
        "note": access_request.note,
        "status": access_request.status,
        "createdAt": access_request.created_at.isoformat() if access_request.created_at else None,
        "invitedAt": access_request.invited_at.isoformat() if access_request.invited_at else None,
        "invitationId": access_request.invitation_id,
    }


def alpha_invitation_to_dict(invitation: AlphaInvitation) -> dict[str, Any]:
    return {
        "id": invitation.id,
        "email": normalize_email(invitation.email),
        "status": invitation.status,
        "expiresAt": invitation.expires_at.isoformat() if invitation.expires_at else None,
        "acceptedAt": invitation.accepted_at.isoformat() if invitation.accepted_at else None,
        "createdUserId": invitation.created_user_id,
        "createdAt": invitation.created_at.isoformat() if invitation.created_at else None,
    }
