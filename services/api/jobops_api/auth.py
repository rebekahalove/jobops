from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from jobops_api.db.models import CandidateProfile, InviteToken, Tenant, User, UserSession, WorkspaceMembership
from jobops_api.db.session import get_db_session


SESSION_COOKIE_NAME = "jobops_session"
SESSION_TTL = timedelta(hours=12)
INVITE_TTL = timedelta(days=14)
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,39}$")
PASSWORD_HASH_VERSION = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 260_000
MIN_PASSWORD_LENGTH = 12


@dataclass(frozen=True)
class AuthContext:
    user: User
    tenant: Tenant
    candidate_profile: CandidateProfile
    session: UserSession

    @property
    def user_id(self) -> str:
        return self.user.id

    @property
    def tenant_id(self) -> str:
        return self.tenant.id

    @property
    def workspace_id(self) -> str:
        return self.tenant.id


@dataclass(frozen=True)
class CreatedInvite:
    invite: InviteToken
    raw_token: str


def create_alpha_invite(
    session: Session,
    *,
    email: str,
    display_name: str | None = None,
    workspace_slug: str | None = None,
    created_by: str | None = None,
    expires_at: datetime | None = None,
) -> CreatedInvite:
    raw_token = secrets.token_urlsafe(48)
    invite = InviteToken(
        token_hash=hash_token(raw_token),
        email=normalize_email(email),
        username=None,
        display_name=(display_name or "").strip(),
        workspace_slug=slugify(workspace_slug) if workspace_slug else "",
        created_by=clean_text(created_by),
        expires_at=expires_at or now_utc() + INVITE_TTL,
    )
    session.add(invite)
    session.flush()
    return CreatedInvite(invite=invite, raw_token=raw_token)


def accept_alpha_invite(
    session: Session,
    raw_token: str,
    *,
    username: str,
    password: str,
    display_name: str,
) -> tuple[AuthContext, str]:
    invite = session.scalar(select(InviteToken).where(InviteToken.token_hash == hash_token(raw_token)))
    if invite is None or invite.revoked_at is not None or invite.used_at is not None:
        raise HTTPException(status_code=404, detail="Invite token was not found or is no longer valid.")
    if invite.expires_at is not None and aware_utc(invite.expires_at) <= now_utc():
        raise HTTPException(status_code=410, detail="Invite token has expired.")

    normalized_username = normalize_username(username)
    ensure_username_available(session, normalized_username)
    validate_password(password)
    resolved_display_name = display_name.strip() or invite.display_name or normalized_username
    workspace_slug = invite.workspace_slug or normalized_username

    user = get_or_create_user(session, email=invite.email, username=normalized_username, display_name=resolved_display_name)
    user.password_hash = hash_password(password)
    user.password_reset_required = False
    user.password_expires_at = None
    tenant = get_or_create_workspace(session, slug=workspace_slug, display_name=resolved_display_name)
    get_or_create_membership(session, user_id=user.id, tenant_id=tenant.id)
    candidate_profile = get_or_create_workspace_profile(session, tenant=tenant, username=normalized_username, display_name=resolved_display_name)

    invite.username = normalized_username
    invite.display_name = resolved_display_name
    invite.used_at = now_utc()
    auth_context, raw_session_token = create_session_for_user(
        session,
        user=user,
        tenant=tenant,
        candidate_profile=candidate_profile,
    )
    session.flush()
    return auth_context, raw_session_token


def create_session_for_user(
    session: Session,
    *,
    user: User,
    tenant: Tenant,
    candidate_profile: CandidateProfile | None = None,
) -> tuple[AuthContext, str]:
    candidate_profile = candidate_profile or get_or_create_workspace_profile(
        session,
        tenant=tenant,
        username=user.username,
        display_name=user.display_name,
    )
    raw_session_token = secrets.token_urlsafe(48)
    session_row = UserSession(
        token_hash=hash_token(raw_session_token),
        user_id=user.id,
        tenant_id=tenant.id,
        expires_at=now_utc() + SESSION_TTL,
        last_seen_at=now_utc(),
    )
    session.add(session_row)
    session.flush()
    return AuthContext(user=user, tenant=tenant, candidate_profile=candidate_profile, session=session_row), raw_session_token


def authenticate_session(session: Session, raw_session_token: str | None) -> AuthContext | None:
    if not raw_session_token:
        return None
    session_row = session.scalar(select(UserSession).where(UserSession.token_hash == hash_token(raw_session_token)))
    if session_row is None or session_row.revoked_at is not None or aware_utc(session_row.expires_at) <= now_utc():
        return None

    user = session.get(User, session_row.user_id)
    tenant = session.get(Tenant, session_row.tenant_id)
    if user is None or tenant is None or user.status != "active" or user.password_reset_required:
        return None
    if user.password_expires_at is not None and aware_utc(user.password_expires_at) <= now_utc():
        return None

    candidate_profile = get_default_workspace_profile(session, tenant.id)
    if candidate_profile is None:
        candidate_profile = get_or_create_workspace_profile(
            session,
            tenant=tenant,
            username=user.username,
            display_name=user.display_name,
        )

    session_row.last_seen_at = now_utc()
    session.flush()
    return AuthContext(user=user, tenant=tenant, candidate_profile=candidate_profile, session=session_row)


def require_auth_context(
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
    session: Session = Depends(get_db_session),
) -> AuthContext:
    auth_context = authenticate_session(session, session_token)
    if auth_context is None:
        raise HTTPException(status_code=401, detail="JobOps authentication is required.")
    return auth_context


def revoke_session(session: Session, raw_session_token: str | None) -> None:
    if not raw_session_token:
        return
    session_row = session.scalar(select(UserSession).where(UserSession.token_hash == hash_token(raw_session_token)))
    if session_row is not None:
        session_row.revoked_at = now_utc()
        session.flush()


def set_session_cookie(response: Response, raw_session_token: str, *, secure: bool) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        raw_session_token,
        httponly=True,
        max_age=int(SESSION_TTL.total_seconds()),
        path="/",
        samesite="lax",
        secure=secure,
    )


def clear_session_cookie(response: Response, *, secure: bool) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/", samesite="lax", secure=secure, httponly=True)


def create_session_for_username(session: Session, *, username: str, password: str) -> tuple[AuthContext, str]:
    normalized_username = normalize_username(username)
    user = session.scalar(select(User).where(User.username == normalized_username))
    if user is None or user.status != "active":
        raise HTTPException(status_code=404, detail="No active JobOps user exists for that username.")
    verify_user_password_or_raise(user, password)
    if user.password_reset_required or (user.password_expires_at is not None and aware_utc(user.password_expires_at) <= now_utc()):
        raise HTTPException(status_code=403, detail={"code": "password_reset_required", "message": "Password reset is required before signing in."})

    memberships = list(
        session.scalars(select(WorkspaceMembership).where(WorkspaceMembership.user_id == user.id).order_by(WorkspaceMembership.created_at.asc()))
    )
    if not memberships:
        raise HTTPException(status_code=409, detail="That JobOps user does not have a workspace yet.")
    if len(memberships) > 1:
        raise HTTPException(status_code=409, detail="Multiple workspaces are not supported in the alpha login flow yet.")

    tenant = session.get(Tenant, memberships[0].tenant_id)
    if tenant is None:
        raise HTTPException(status_code=409, detail="The selected workspace no longer exists.")
    profile = get_or_create_workspace_profile(session, tenant=tenant, username=user.username, display_name=user.display_name)
    return create_session_for_user(session, user=user, tenant=tenant, candidate_profile=profile)


def get_or_create_user(session: Session, *, email: str, username: str, display_name: str) -> User:
    normalized_email = normalize_email(email)
    normalized_username = normalize_username(username)
    user = session.scalar(select(User).where(User.username == normalized_username))
    email_user = session.scalar(select(User).where(User.email == normalized_email))
    if user is not None and email_user is not None and user.id != email_user.id:
        raise HTTPException(status_code=409, detail="Username and email belong to different JobOps users.")
    if email_user is not None and email_user.username != normalized_username:
        raise HTTPException(status_code=409, detail="Email already belongs to a different JobOps username.")
    user = user or email_user
    if user is not None:
        user.username = normalized_username
        user.email = normalized_email
        user.display_name = display_name.strip() or user.display_name
        user.status = "active"
        return user
    user = User(email=normalized_email, username=normalized_username, display_name=display_name.strip() or normalized_email)
    session.add(user)
    session.flush()
    return user


def get_or_create_workspace(session: Session, *, slug: str, display_name: str) -> Tenant:
    workspace_slug = slugify(slug)
    tenant = session.scalar(select(Tenant).where(Tenant.slug == workspace_slug))
    if tenant is not None:
        return tenant
    tenant = Tenant(name=display_name.strip() or workspace_slug, slug=workspace_slug)
    session.add(tenant)
    session.flush()
    return tenant


def get_or_create_membership(session: Session, *, user_id: str, tenant_id: str) -> WorkspaceMembership:
    membership = session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.tenant_id == tenant_id,
        )
    )
    if membership is not None:
        return membership
    membership = WorkspaceMembership(user_id=user_id, tenant_id=tenant_id, role="owner")
    session.add(membership)
    session.flush()
    return membership


def get_default_workspace_profile(session: Session, tenant_id: str) -> CandidateProfile | None:
    return session.scalar(
        select(CandidateProfile)
        .where(CandidateProfile.tenant_id == tenant_id)
        .order_by(CandidateProfile.created_at.asc())
        .limit(1)
    )


def get_or_create_workspace_profile(session: Session, *, tenant: Tenant, username: str, display_name: str) -> CandidateProfile:
    candidate_profile = get_default_workspace_profile(session, tenant.id)
    if candidate_profile is not None:
        return candidate_profile
    candidate_profile = CandidateProfile(
        tenant_id=tenant.id,
        slug=normalize_username(username),
        display_name=display_name.strip() or tenant.name,
        headline="Candidate profile setup in progress",
        summary="Private JobOps workspace profile.",
        profile_status="draft",
    )
    session.add(candidate_profile)
    session.flush()
    return candidate_profile


def seed_initial_user(
    session: Session,
    *,
    email: str,
    username: str,
    display_name: str,
    password: str,
    password_reset_required: bool = True,
    workspace_slug: str | None = None,
) -> AuthContext:
    normalized_username = normalize_username(username)
    validate_password(password)
    user = get_or_create_user(session, email=email, username=normalized_username, display_name=display_name)
    user.password_hash = hash_password(password)
    user.password_reset_required = password_reset_required
    user.password_expires_at = now_utc() if password_reset_required else None
    if password_reset_required:
        session.query(UserSession).filter(UserSession.user_id == user.id, UserSession.revoked_at.is_(None)).update(
            {"revoked_at": now_utc()},
            synchronize_session=False,
        )
    workspace_slug = workspace_slug or normalized_username
    tenant = get_or_create_workspace(session, slug=workspace_slug, display_name=display_name)
    get_or_create_membership(session, user_id=user.id, tenant_id=tenant.id)
    profile = get_or_create_workspace_profile(session, tenant=tenant, username=normalized_username, display_name=display_name)
    return AuthContext(user=user, tenant=tenant, candidate_profile=profile, session=UserSession())


def auth_context_to_dict(auth_context: AuthContext) -> dict[str, object]:
    return {
        "user": {
            "id": auth_context.user.id,
            "email": auth_context.user.email,
            "username": auth_context.user.username,
            "displayName": auth_context.user.display_name,
            "passwordResetRequired": auth_context.user.password_reset_required,
        },
        "workspace": {
            "id": auth_context.tenant.id,
            "slug": auth_context.tenant.slug,
            "name": auth_context.tenant.name,
        },
        "candidateProfile": {
            "id": auth_context.candidate_profile.id,
            "slug": auth_context.candidate_profile.slug,
            "displayName": auth_context.candidate_profile.display_name,
        },
    }


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def normalize_email(email: str) -> str:
    normalized = email.strip().casefold()
    if "@" not in normalized or len(normalized) > 320:
        raise HTTPException(status_code=400, detail="A valid email address is required.")
    return normalized


def normalize_username(username: str) -> str:
    normalized = username.strip().casefold()
    if not USERNAME_RE.fullmatch(normalized):
        raise HTTPException(
            status_code=400,
            detail="Username must be 3-40 lowercase URL-safe characters: letters, numbers, hyphen, or underscore.",
        )
    return normalized


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=400, detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")


def hash_password(password: str) -> str:
    validate_password(password)
    salt = secrets.token_urlsafe(18)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PASSWORD_ITERATIONS)
    return f"{PASSWORD_HASH_VERSION}${PASSWORD_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return False
    try:
        version, iterations_text, salt, digest_hex = stored_hash.split("$", 3)
        if version != PASSWORD_HASH_VERSION:
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations_text))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def verify_user_password_or_raise(user: User, password: str) -> None:
    if not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Username or password is incorrect.")


def reset_user_password(session: Session, *, username: str, current_password: str, new_password: str) -> tuple[AuthContext, str]:
    normalized_username = normalize_username(username)
    user = session.scalar(select(User).where(User.username == normalized_username))
    if user is None or user.status != "active":
        raise HTTPException(status_code=404, detail="No active JobOps user exists for that username.")
    verify_user_password_or_raise(user, current_password)
    validate_password(new_password)
    user.password_hash = hash_password(new_password)
    user.password_reset_required = False
    user.password_expires_at = None
    session.flush()
    return create_session_for_username(session, username=normalized_username, password=new_password)


def ensure_username_available(session: Session, username: str) -> None:
    if session.scalar(select(User.id).where(User.username == username)):
        raise HTTPException(status_code=409, detail="Username is already in use.")
    active_invite = session.scalar(
        select(InviteToken.id).where(
            InviteToken.username == username,
            InviteToken.used_at.is_(None),
            InviteToken.revoked_at.is_(None),
        )
    )
    if active_invite:
        raise HTTPException(status_code=409, detail="An active invite already exists for that username.")


def workspace_slug_or_default(workspace_slug: str | None, username: str) -> str:
    return slugify(workspace_slug or username)


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().casefold())
    normalized = normalized.strip("-")
    if not normalized:
        raise HTTPException(status_code=400, detail="Workspace slug is required.")
    return normalized[:120]


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
