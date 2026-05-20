from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(120), unique=True)

    candidate_profiles: Mapped[list[CandidateProfile]] = relationship(back_populates="tenant", cascade="all, delete-orphan")


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_email", "email", unique=True),
        Index("ix_users_username", "username", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320))
    username: Mapped[str] = mapped_column(String(40))
    display_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_reset_required: Mapped[bool] = mapped_column(Boolean, default=False)
    password_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="active")

    memberships: Mapped[list[WorkspaceMembership]] = relationship(back_populates="user", cascade="all, delete-orphan")
    sessions: Mapped[list[UserSession]] = relationship(back_populates="user", cascade="all, delete-orphan")


class WorkspaceMembership(Base, TimestampMixin):
    __tablename__ = "workspace_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "tenant_id", name="uq_workspace_memberships_user_tenant"),
        Index("ix_workspace_memberships_tenant", "tenant_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(40), default="owner")

    user: Mapped[User] = relationship(back_populates="memberships")
    tenant: Mapped[Tenant] = relationship()


class InviteToken(Base, TimestampMixin):
    __tablename__ = "invite_tokens"
    __table_args__ = (
        Index("ix_invite_tokens_token_hash", "token_hash", unique=True),
        Index("ix_invite_tokens_email", "email"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    token_hash: Mapped[str] = mapped_column(String(64))
    email: Mapped[str] = mapped_column(String(320))
    username: Mapped[str | None] = mapped_column(String(40), nullable=True)
    display_name: Mapped[str] = mapped_column(String(200))
    workspace_slug: Mapped[str] = mapped_column(String(120))
    created_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AlphaAccessRequest(Base):
    __tablename__ = "alpha_access_requests"
    __table_args__ = (
        Index("ix_alpha_access_requests_email_created", "email", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserSession(Base):
    __tablename__ = "user_sessions"
    __table_args__ = (
        Index("ix_user_sessions_token_hash", "token_hash", unique=True),
        Index("ix_user_sessions_user_tenant", "user_id", "tenant_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    token_hash: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="sessions")
    tenant: Mapped[Tenant] = relationship()


class CandidateProfile(Base, TimestampMixin):
    __tablename__ = "candidate_profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_candidate_profiles_tenant_slug"),
        Index("ix_candidate_profiles_slug", "slug"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    slug: Mapped[str] = mapped_column(String(120))
    display_name: Mapped[str] = mapped_column(String(200))
    headline: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(Text, default="")
    profile_status: Mapped[str] = mapped_column(String(40), default="draft")

    tenant: Mapped[Tenant] = relationship(back_populates="candidate_profiles")
    facts: Mapped[list[ProfileFact]] = relationship(back_populates="candidate_profile", cascade="all, delete-orphan")
    applications: Mapped[list[Application]] = relationship(back_populates="candidate_profile", cascade="all, delete-orphan")
    target_companies: Mapped[list[TargetCompany]] = relationship(back_populates="candidate_profile", cascade="all, delete-orphan")


class Domain(Base):
    __tablename__ = "domains"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"))
    hostname: Mapped[str] = mapped_column(String(255), unique=True)
    purpose: Mapped[str] = mapped_column(String(40), default="public_profile")
    verification_status: Mapped[str] = mapped_column(String(40), default="pending")
    is_canonical: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RoleTarget(Base, TimestampMixin):
    __tablename__ = "role_targets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"))
    profile_intake_session_id: Mapped[str | None] = mapped_column(ForeignKey("profile_intake_sessions.id", ondelete="SET NULL"), nullable=True)
    target_titles: Mapped[list[str]] = mapped_column(JSON, default=list)
    role_families: Mapped[list[str]] = mapped_column(JSON, default=list)
    seniority: Mapped[str | None] = mapped_column(String(80), nullable=True)
    preferred_locations: Mapped[list[str]] = mapped_column(JSON, default=list)
    work_modes: Mapped[list[str]] = mapped_column(JSON, default=list)
    constraints: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(40), default="model")
    review_status: Mapped[str] = mapped_column(String(40), default="needs_review")
    visibility: Mapped[str] = mapped_column(String(40), default="private")
    publication_status: Mapped[str] = mapped_column(String(40), default="not_published")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class TargetCompany(Base, TimestampMixin):
    __tablename__ = "target_companies"
    __table_args__ = (
        UniqueConstraint("candidate_profile_id", "name", name="uq_target_companies_profile_name"),
        Index("ix_target_companies_profile_name", "candidate_profile_id", "name"),
        Index("ix_target_companies_profile_normalized_name", "candidate_profile_id", "normalized_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(240))
    normalized_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    website_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    careers_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_listings_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    headquarters_city: Mapped[str | None] = mapped_column(String(160), nullable=True)
    headquarters_country: Mapped[str | None] = mapped_column(String(160), nullable=True)
    operating_countries: Mapped[list[str]] = mapped_column(JSON, default=list)
    hiring_locations: Mapped[list[str]] = mapped_column(JSON, default=list)
    remote_policy: Mapped[str] = mapped_column(String(40), default="unknown")
    role_fit_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    mission_fit_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    fit_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_urls: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    discovery_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    search_queries_used: Mapped[list[str]] = mapped_column(JSON, default=list)
    provider_grounding_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    discovered_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    derivation_status: Mapped[str] = mapped_column(String(40), default="user_entered")
    review_status: Mapped[str] = mapped_column(String(40), default="reviewed")
    notes: Mapped[str] = mapped_column(Text, default="")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    candidate_profile: Mapped[CandidateProfile] = relationship(back_populates="target_companies")
    job_roles: Mapped[list[JobRole]] = relationship(back_populates="target_company", cascade="all, delete-orphan")
    applications: Mapped[list[Application]] = relationship(back_populates="target_company")


class JobRole(Base, TimestampMixin):
    __tablename__ = "job_roles"
    __table_args__ = (
        Index("ix_job_roles_profile_status", "candidate_profile_id", "status"),
        Index("ix_job_roles_company_title", "target_company_id", "title"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"))
    target_company_id: Mapped[str | None] = mapped_column(ForeignKey("target_companies.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(240))
    job_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(240), nullable=True)
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="saved")
    raw_description_artifact_uri: Mapped[str | None] = mapped_column(Text, nullable=True)

    target_company: Mapped[TargetCompany | None] = relationship(back_populates="job_roles")
    applications: Mapped[list[Application]] = relationship(back_populates="job_role")


class Application(Base, TimestampMixin):
    __tablename__ = "applications"
    __table_args__ = (
        Index("ix_applications_profile_status", "candidate_profile_id", "status"),
        Index("ix_applications_next_follow_up", "candidate_profile_id", "next_follow_up_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"))
    target_company_id: Mapped[str | None] = mapped_column(ForeignKey("target_companies.id", ondelete="SET NULL"), nullable=True)
    job_role_id: Mapped[str | None] = mapped_column(ForeignKey("job_roles.id", ondelete="SET NULL"), nullable=True)
    company_name: Mapped[str] = mapped_column(String(240))
    job_title: Mapped[str] = mapped_column(String(240))
    job_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(240), nullable=True)
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    date_applied: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="saved")
    notes: Mapped[str] = mapped_column(Text, default="")
    next_follow_up_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    candidate_profile: Mapped[CandidateProfile] = relationship(back_populates="applications")
    target_company: Mapped[TargetCompany | None] = relationship(back_populates="applications")
    job_role: Mapped[JobRole | None] = relationship(back_populates="applications")
    events: Mapped[list[ApplicationEvent]] = relationship(back_populates="application", cascade="all, delete-orphan")


class ApplicationEvent(Base):
    __tablename__ = "application_events"
    __table_args__ = (
        Index("ix_application_events_application_date", "application_id", "event_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(String(80))
    event_date: Mapped[date] = mapped_column(Date)
    notes: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    application: Mapped[Application] = relationship(back_populates="events")


class ProfileFact(Base, TimestampMixin):
    __tablename__ = "profile_facts"
    __table_args__ = (
        Index("ix_profile_facts_profile_status", "candidate_profile_id", "verification_status", "visibility"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"))
    fact_type: Mapped[str] = mapped_column(String(80))
    claim: Mapped[str] = mapped_column(Text)
    structured_value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(120))
    visibility: Mapped[str] = mapped_column(String(40), default="private")
    verification_status: Mapped[str] = mapped_column(String(40), default="draft")

    candidate_profile: Mapped[CandidateProfile] = relationship(back_populates="facts")


class ProfileFactDraft(Base, TimestampMixin):
    __tablename__ = "profile_fact_drafts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"))
    profile_intake_session_id: Mapped[str | None] = mapped_column(ForeignKey("profile_intake_sessions.id", ondelete="SET NULL"), nullable=True)
    claim: Mapped[str] = mapped_column(Text)
    fact_type: Mapped[str] = mapped_column(String(80))
    structured_value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(120))
    confidence: Mapped[str] = mapped_column(String(40), default="unknown")
    suggested_visibility: Mapped[str] = mapped_column(String(40), default="private")
    review_status: Mapped[str] = mapped_column(String(40), default="needs_review")


class SkillClaim(Base, TimestampMixin):
    __tablename__ = "skill_claims"
    __table_args__ = (
        Index("ix_skill_claims_profile_skill", "candidate_profile_id", "skill_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"))
    profile_intake_session_id: Mapped[str | None] = mapped_column(ForeignKey("profile_intake_sessions.id", ondelete="SET NULL"), nullable=True)
    skill_name: Mapped[str] = mapped_column(String(160))
    skill_category: Mapped[str] = mapped_column(String(120))
    years_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    years_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recency: Mapped[str | None] = mapped_column(String(80), nullable=True)
    proficiency: Mapped[str | None] = mapped_column(String(80), nullable=True)
    evidence_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_fact_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(40), default="model")
    visibility: Mapped[str] = mapped_column(String(40), default="private")
    verification_status: Mapped[str] = mapped_column(String(40), default="draft")
    publication_status: Mapped[str] = mapped_column(String(40), default="not_published")


class ResumeArtifact(Base):
    __tablename__ = "resume_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(255))
    storage_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_status: Mapped[str] = mapped_column(String(40), default="pending")
    parsed_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProfileIntakeSession(Base, TimestampMixin):
    __tablename__ = "profile_intake_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(40), default="active")
    target_role_summary: Mapped[str] = mapped_column(Text, default="")
    redacted_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_turn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProfileIntakeEvent(Base):
    __tablename__ = "profile_intake_events"
    __table_args__ = (
        Index("ix_profile_intake_events_session_created", "session_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("profile_intake_sessions.id", ondelete="CASCADE"))
    candidate_profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(40))
    event_type: Mapped[str] = mapped_column(String(80))
    redacted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_text_artifact_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_run_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExperienceProjectDraft(Base, TimestampMixin):
    __tablename__ = "experience_project_drafts"
    __table_args__ = (
        Index("ix_experience_project_drafts_session", "profile_intake_session_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"))
    profile_intake_session_id: Mapped[str | None] = mapped_column(ForeignKey("profile_intake_sessions.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    organization: Mapped[str | None] = mapped_column(String(200), nullable=True)
    start_date: Mapped[str | None] = mapped_column(String(80), nullable=True)
    end_date: Mapped[str | None] = mapped_column(String(80), nullable=True)
    location: Mapped[str | None] = mapped_column(String(160), nullable=True)
    summary: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(40), default="model")
    visibility: Mapped[str] = mapped_column(String(40), default="private")
    review_status: Mapped[str] = mapped_column(String(40), default="needs_review")
    publication_status: Mapped[str] = mapped_column(String(40), default="not_published")
    structured_value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class EvidenceArtifact(Base):
    __tablename__ = "evidence_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"))
    profile_intake_session_id: Mapped[str | None] = mapped_column(ForeignKey("profile_intake_sessions.id", ondelete="SET NULL"), nullable=True)
    artifact_type: Mapped[str] = mapped_column(String(80))
    label: Mapped[str] = mapped_column(String(255))
    uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(40), default="model")
    visibility: Mapped[str] = mapped_column(String(40), default="private")
    review_status: Mapped[str] = mapped_column(String(40), default="needs_review")
    publication_status: Mapped[str] = mapped_column(String(40), default="not_published")
    artifact_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UsageEvent(Base):
    __tablename__ = "usage_events"
    __table_args__ = (
        Index("ix_usage_events_tenant_event", "tenant_id", "event_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    candidate_profile_id: Mapped[str | None] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"), nullable=True)
    event_name: Mapped[str] = mapped_column(String(120))
    event_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CommandInteractionLog(Base):
    __tablename__ = "command_interaction_logs"
    __table_args__ = (
        Index("ix_command_interaction_logs_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    candidate_profile_id: Mapped[str | None] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="SET NULL"), nullable=True)
    user_message: Mapped[str] = mapped_column(Text)
    route_selected: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model_provider: Mapped[str | None] = mapped_column(String(120), nullable=True)
    parsed_action_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    validation_result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    action_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    final_response: Mapped[str] = mapped_column(Text, default="")
    error_details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
