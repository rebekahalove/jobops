from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func, text
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
        CheckConstraint("user_type IN ('user', 'admin')", name="ck_users_user_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320))
    username: Mapped[str] = mapped_column(String(40))
    display_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_reset_required: Mapped[bool] = mapped_column(Boolean, default=False)
    password_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="active")
    user_type: Mapped[str] = mapped_column(String(40), default="user")

    memberships: Mapped[list[WorkspaceMembership]] = relationship(back_populates="user", cascade="all, delete-orphan")
    sessions: Mapped[list[UserSession]] = relationship(back_populates="user", cascade="all, delete-orphan")
    password_reset_tokens: Mapped[list[PasswordResetToken]] = relationship(back_populates="user", cascade="all, delete-orphan")
    alpha_invitations_sent: Mapped[list[AlphaInvitation]] = relationship(
        foreign_keys="AlphaInvitation.invited_by_user_id",
        back_populates="invited_by",
    )


class WorkspaceMembership(Base, TimestampMixin):
    __tablename__ = "workspace_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "tenant_id", name="uq_workspace_memberships_user_tenant"),
        Index("ix_workspace_memberships_tenant", "tenant_id"),
        Index("ix_workspace_memberships_user_created", "user_id", "created_at"),
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
        Index("ix_invite_tokens_username_active", "username", "used_at", "revoked_at"),
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
        Index("ix_alpha_access_requests_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320))
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), default="pending")
    invited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invitation_id: Mapped[str | None] = mapped_column(ForeignKey("alpha_invitations.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    invitation: Mapped[AlphaInvitation | None] = relationship(back_populates="access_requests")


class AlphaInvitation(Base, TimestampMixin):
    __tablename__ = "alpha_invitations"
    __table_args__ = (
        Index("ix_alpha_invitations_token_hash", "token_hash", unique=True),
        Index("ix_alpha_invitations_email_status", "email", "status"),
        CheckConstraint("status IN ('pending', 'accepted', 'expired', 'revoked')", name="ck_alpha_invitations_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320))
    token_hash: Mapped[str] = mapped_column(String(64))
    invited_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    invited_by: Mapped[User | None] = relationship(
        foreign_keys=[invited_by_user_id],
        back_populates="alpha_invitations_sent",
    )
    created_user: Mapped[User | None] = relationship(foreign_keys=[created_user_id])
    access_requests: Mapped[list[AlphaAccessRequest]] = relationship(back_populates="invitation")


class UserSession(Base):
    __tablename__ = "user_sessions"
    __table_args__ = (
        Index("ix_user_sessions_token_hash", "token_hash", unique=True),
        Index("ix_user_sessions_user_tenant", "user_id", "tenant_id"),
        Index("ix_user_sessions_user_revoked", "user_id", "revoked_at"),
        Index("ix_user_sessions_tenant", "tenant_id"),
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


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    __table_args__ = (
        Index("ix_password_reset_tokens_token_hash", "token_hash", unique=True),
        Index("ix_password_reset_tokens_user", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    token_hash: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="password_reset_tokens")


class CandidateProfile(Base, TimestampMixin):
    __tablename__ = "candidate_profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_candidate_profiles_tenant_slug"),
        Index("ix_candidate_profiles_slug", "slug"),
        Index("ix_candidate_profiles_tenant_created", "tenant_id", "created_at"),
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
    application_material_bundles: Mapped[list[ApplicationMaterialBundle]] = relationship(
        back_populates="candidate_profile",
        cascade="all, delete-orphan",
    )
    candidate_companies: Mapped[list[CandidateCompany]] = relationship(back_populates="candidate_profile", cascade="all, delete-orphan")
    saved_jobs: Mapped[list[CandidateSavedJob]] = relationship(back_populates="candidate_profile", cascade="all, delete-orphan")
    job_search_runs: Mapped[list[JobSearchRun]] = relationship(back_populates="candidate_profile", cascade="all, delete-orphan")


class Domain(Base):
    __tablename__ = "domains"
    __table_args__ = (
        Index("ix_domains_candidate_profile", "candidate_profile_id"),
    )

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
    __table_args__ = (
        Index("ix_role_targets_session_active_updated", "profile_intake_session_id", "is_active", "updated_at"),
        Index("ix_role_targets_profile_publication_active", "candidate_profile_id", "publication_status", "visibility", "is_active"),
        Index("ix_role_targets_profile_review", "candidate_profile_id", "review_status"),
    )

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


class ProfileFieldValue(Base, TimestampMixin):
    __tablename__ = "profile_field_values"
    __table_args__ = (
        Index("ix_profile_field_values_profile_field", "candidate_profile_id", "field_group", "field_name", "lifecycle_status"),
        Index(
            "ix_profile_field_values_latest",
            "candidate_profile_id",
            "field_group",
            "field_name",
            "lifecycle_status",
            "visibility",
            "updated_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"))
    field_group: Mapped[str] = mapped_column(String(80))
    field_name: Mapped[str] = mapped_column(String(120))
    value_text: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(40), default="user")
    lifecycle_status: Mapped[str] = mapped_column(String(40), default="generated")
    visibility: Mapped[str | None] = mapped_column(String(40), nullable=True)
    original_value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    archive_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    field_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Company(Base, TimestampMixin):
    __tablename__ = "companies"
    __table_args__ = (
        UniqueConstraint("normalized_domain", name="uq_companies_normalized_domain"),
        Index("ix_companies_normalized_name", "normalized_name"),
        Index("ix_companies_last_seen", "last_seen_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(240))
    normalized_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    normalized_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    website_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    careers_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_listings_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    headquarters_city: Mapped[str | None] = mapped_column(String(160), nullable=True)
    headquarters_country: Mapped[str | None] = mapped_column(String(160), nullable=True)
    operating_countries: Mapped[list[str]] = mapped_column(JSON, default=list)
    hiring_locations: Mapped[list[str]] = mapped_column(JSON, default=list)
    remote_policy: Mapped[str] = mapped_column(String(40), default="unknown")
    source_urls: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_confidence: Mapped[str] = mapped_column(String(40), default="medium")
    greenhouse_board_token: Mapped[str | None] = mapped_column(String(240), nullable=True)
    ashby_board_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    lever_slug: Mapped[str | None] = mapped_column(String(240), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    candidate_links: Mapped[list[CandidateCompany]] = relationship(back_populates="company", cascade="all, delete-orphan")
    job_postings: Mapped[list[JobPosting]] = relationship(back_populates="company")
    job_listings: Mapped[list[JobListing]] = relationship(back_populates="company")
    job_roles: Mapped[list[JobRole]] = relationship(back_populates="company")
    applications: Mapped[list[Application]] = relationship(back_populates="company")


class CandidateCompany(Base, TimestampMixin):
    __tablename__ = "candidate_companies"
    __table_args__ = (
        UniqueConstraint("candidate_profile_id", "company_id", name="uq_candidate_companies_profile_company"),
        Index("ix_candidate_companies_profile_added", "candidate_profile_id", "added_at"),
        Index("ix_candidate_companies_profile_review_added", "candidate_profile_id", "review_status", "added_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"))
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    review_status: Mapped[str] = mapped_column(String(40), default="new")
    derivation_status: Mapped[str] = mapped_column(String(40), default="model_derived")
    fit_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    role_fit_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    mission_fit_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    discovery_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    search_queries_used: Mapped[list[str]] = mapped_column(JSON, default=list)
    provider_grounding_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    discovered_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    personal_source_urls: Mapped[list[str]] = mapped_column(JSON, default=list)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    candidate_profile: Mapped[CandidateProfile] = relationship(back_populates="candidate_companies")
    company: Mapped[Company] = relationship(back_populates="candidate_links")

    @property
    def name(self) -> str:
        return self.company.name


class JobPosting(Base, TimestampMixin):
    __tablename__ = "job_postings"
    __table_args__ = (
        UniqueConstraint("normalized_url", name="uq_job_postings_normalized_url"),
        Index("ix_job_postings_company_title", "company_name", "title"),
        Index("ix_job_postings_last_seen", "last_seen_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(240))
    company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), nullable=True)
    company_name: Mapped[str] = mapped_column(String(240))
    job_url: Mapped[str] = mapped_column(Text)
    canonical_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    apply_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_url: Mapped[str] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_provider: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provider_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    source_result_id: Mapped[str | None] = mapped_column(String(240), nullable=True)
    source_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_raw_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    company_website_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_careers_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    ats_provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    ats_board_token: Mapped[str | None] = mapped_column(String(240), nullable=True)
    provenance: Mapped[str] = mapped_column(String(40), default="unknown")
    location: Mapped[str | None] = mapped_column(String(240), nullable=True)
    remote_work_mode: Mapped[str | None] = mapped_column(String(80), nullable=True)
    employment_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    salary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    full_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    discovered_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    url_verification_status: Mapped[str] = mapped_column(String(60), default="unverified")
    url_verification_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    url_verification_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    posting_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    company: Mapped[Company | None] = relationship(back_populates="job_postings")
    saved_links: Mapped[list[CandidateSavedJob]] = relationship(back_populates="job", cascade="all, delete-orphan")
    applications: Mapped[list[Application]] = relationship(back_populates="job")


class CandidateSavedJob(Base, TimestampMixin):
    __tablename__ = "candidate_saved_jobs"
    __table_args__ = (
        UniqueConstraint("candidate_profile_id", "job_id", name="uq_candidate_saved_jobs_profile_job"),
        Index(
            "uq_candidate_saved_jobs_profile_listing",
            "candidate_profile_id",
            "job_listing_id",
            unique=True,
            sqlite_where=text("job_listing_id IS NOT NULL"),
            postgresql_where=text("job_listing_id IS NOT NULL"),
        ),
        Index("ix_candidate_saved_jobs_profile_added", "candidate_profile_id", "added_at"),
        Index("ix_candidate_saved_jobs_profile_status_added", "candidate_profile_id", "status", "added_at"),
        Index("ix_candidate_saved_jobs_profile_status", "candidate_profile_id", "status"),
        Index("ix_candidate_saved_jobs_profile_listing", "candidate_profile_id", "job_listing_id"),
        Index("ix_candidate_saved_jobs_job_listing", "job_listing_id"),
        Index("ix_candidate_saved_jobs_search_run", "job_search_run_id"),
        Index("ix_candidate_saved_jobs_last_model_reviewed", "last_model_reviewed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"))
    job_id: Mapped[str | None] = mapped_column(ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=True)
    job_listing_id: Mapped[str | None] = mapped_column(ForeignKey("job_listings.id", ondelete="CASCADE"), nullable=True)
    job_search_run_id: Mapped[str | None] = mapped_column(ForeignKey("job_search_runs.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="new")
    fit_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_command: Mapped[str | None] = mapped_column(Text, nullable=True)
    discovery_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_model_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    model_selected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    model_rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    model_decision_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_review_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    archived_by_action: Mapped[str | None] = mapped_column(String(120), nullable=True)

    candidate_profile: Mapped[CandidateProfile] = relationship(back_populates="saved_jobs")
    job: Mapped[JobPosting | None] = relationship(back_populates="saved_links")
    job_listing: Mapped[JobListing | None] = relationship()
    job_search_run: Mapped[JobSearchRun | None] = relationship()
    applications: Mapped[list[Application]] = relationship(back_populates="saved_job")
    rejection_reasons: Mapped[list[CandidateJobRejectionReason]] = relationship(
        back_populates="candidate_job",
        cascade="all, delete-orphan",
    )


class CandidateJobRejectionReason(Base):
    __tablename__ = "candidate_job_rejection_reasons"
    __table_args__ = (
        Index("ix_candidate_job_rejection_reasons_candidate_job", "candidate_job_id", "active"),
        Index("ix_candidate_job_rejection_reasons_reason_active", "reason_code", "active"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_job_id: Mapped[str] = mapped_column(ForeignKey("candidate_saved_jobs.id", ondelete="CASCADE"))
    reason_code: Mapped[str] = mapped_column(String(80))
    affected_field: Mapped[str | None] = mapped_column(String(160), nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reset_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reset_by: Mapped[str | None] = mapped_column(String(200), nullable=True)

    candidate_job: Mapped[CandidateSavedJob] = relationship(back_populates="rejection_reasons")


class JobLocationTarget(Base, TimestampMixin):
    __tablename__ = "job_location_targets"
    __table_args__ = (
        UniqueConstraint("normalized_key", name="uq_job_location_targets_normalized_key"),
        Index("ix_job_location_targets_normalized_key", "normalized_key"),
        Index("ix_job_location_targets_country_code", "country_code"),
        Index("ix_job_location_targets_verification_status", "verification_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    display_name: Mapped[str] = mapped_column(String(240))
    normalized_key: Mapped[str] = mapped_column(String(240))
    location_kind: Mapped[str] = mapped_column(String(80), default="raw")
    city: Mapped[str | None] = mapped_column(String(160), nullable=True)
    region: Mapped[str | None] = mapped_column(String(160), nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    country_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    raw_inputs_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    confidence: Mapped[str] = mapped_column(String(40), default="low")
    verification_status: Mapped[str] = mapped_column(String(40), default="needs_review")
    source: Mapped[str] = mapped_column(String(80), default="auto")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    provider_mappings: Mapped[list[JobProviderLocationMapping]] = relationship(
        back_populates="job_location_target",
        cascade="all, delete-orphan",
    )


class JobProviderLocationMapping(Base, TimestampMixin):
    __tablename__ = "job_provider_location_mappings"
    __table_args__ = (
        UniqueConstraint("job_location_target_id", "provider_name", name="uq_job_provider_location_mappings_target_provider"),
        Index(
            "ix_job_provider_location_mappings_provider_request",
            "provider_name",
            "provider_country",
            "provider_where",
        ),
        Index("ix_job_provider_location_mappings_target", "job_location_target_id"),
        Index("ix_job_provider_location_mappings_verification_status", "verification_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_location_target_id: Mapped[str] = mapped_column(ForeignKey("job_location_targets.id", ondelete="CASCADE"))
    provider_name: Mapped[str] = mapped_column(String(120))
    provider_country: Mapped[str | None] = mapped_column(String(16), nullable=True)
    provider_where: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_location: Mapped[str] = mapped_column(String(240))
    confidence: Mapped[str] = mapped_column(String(40), default="low")
    verification_status: Mapped[str] = mapped_column(String(40), default="needs_review")
    source: Mapped[str] = mapped_column(String(80), default="auto")
    diagnostics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    job_location_target: Mapped[JobLocationTarget] = relationship(back_populates="provider_mappings")


class JobListing(Base, TimestampMixin):
    __tablename__ = "job_listings"
    __table_args__ = (
        Index("ix_job_listings_active_last_seen", "is_active", "last_seen_at"),
        Index("ix_job_listings_active_source_updated", "is_active", "source_updated_at"),
        Index("ix_job_listings_company_active", "company_id", "is_active"),
        Index("ix_job_listings_location_target_active", "job_location_target_id", "is_active"),
        Index("ix_job_listings_company_name_active", "company_name", "is_active"),
        Index(
            "ix_job_listings_location_active",
            "location_country",
            "location_region",
            "location_city",
            "is_active",
        ),
        Index("ix_job_listings_location_metro_active", "location_metro", "is_active"),
        Index("ix_job_listings_remote_active", "remote_work_mode", "is_active"),
        Index("ix_job_listings_posting_date", "posting_date"),
        Index("ix_job_listings_title", "title"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(240))
    job_location_target_id: Mapped[str | None] = mapped_column(ForeignKey("job_location_targets.id", ondelete="SET NULL"), nullable=True)
    company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), nullable=True)
    company_name: Mapped[str] = mapped_column(String(240))
    canonical_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    apply_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    location_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    location_display: Mapped[str | None] = mapped_column(String(240), nullable=True)
    location_city: Mapped[str | None] = mapped_column(String(160), nullable=True)
    location_region: Mapped[str | None] = mapped_column(String(160), nullable=True)
    location_country: Mapped[str | None] = mapped_column(String(80), nullable=True)
    location_metro: Mapped[str | None] = mapped_column(String(160), nullable=True)
    location_confidence: Mapped[str | None] = mapped_column(String(40), nullable=True)
    remote_work_mode: Mapped[str | None] = mapped_column(String(80), nullable=True)
    employment_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    salary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    full_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    posting_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_status: Mapped[str | None] = mapped_column(String(80), nullable=True)

    company: Mapped[Company | None] = relationship(back_populates="job_listings")
    job_location_target: Mapped[JobLocationTarget | None] = relationship()
    sources: Mapped[list[JobListingSource]] = relationship(
        back_populates="job_listing",
        cascade="all, delete-orphan",
    )


class JobListingSource(Base, TimestampMixin):
    __tablename__ = "job_listing_sources"
    __table_args__ = (
        Index("ix_job_listing_sources_job_listing", "job_listing_id"),
        Index("ix_job_listing_sources_provider_active", "source_provider", "is_active"),
        Index("ix_job_listing_sources_ats_board_active", "ats_provider", "ats_board_token", "is_active"),
        Index("ix_job_listing_sources_provider_last_seen", "source_provider", "last_seen_at"),
        Index("ix_job_listing_sources_provider_query", "source_provider", "source_query"),
        Index(
            "uq_job_listing_sources_greenhouse_identity",
            "source_provider",
            "ats_board_token",
            "provider_job_id",
            unique=True,
            sqlite_where=text(
                "source_provider = 'greenhouse' AND ats_board_token IS NOT NULL AND provider_job_id IS NOT NULL"
            ),
            postgresql_where=text(
                "source_provider = 'greenhouse' AND ats_board_token IS NOT NULL AND provider_job_id IS NOT NULL"
            ),
        ),
        Index(
            "uq_job_listing_sources_provider_job_id",
            "source_provider",
            "provider_job_id",
            unique=True,
            sqlite_where=text("provider_job_id IS NOT NULL AND source_provider <> 'greenhouse'"),
            postgresql_where=text("provider_job_id IS NOT NULL AND source_provider <> 'greenhouse'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_listing_id: Mapped[str] = mapped_column(ForeignKey("job_listings.id", ondelete="CASCADE"))
    source_provider: Mapped[str] = mapped_column(String(120))
    provider_type: Mapped[str] = mapped_column(String(60))
    provider_job_id: Mapped[str | None] = mapped_column(String(240), nullable=True)
    source_result_id: Mapped[str | None] = mapped_column(String(240), nullable=True)
    ats_provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    ats_board_token: Mapped[str | None] = mapped_column(String(240), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    apply_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonical_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_location: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_country: Mapped[str | None] = mapped_column(String(16), nullable=True)
    raw_location: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)

    job_listing: Mapped[JobListing] = relationship(back_populates="sources")


class JobSyncSignature(Base, TimestampMixin):
    __tablename__ = "job_sync_signatures"
    __table_args__ = (
        UniqueConstraint("sync_key", name="uq_job_sync_signatures_sync_key"),
        Index("ix_job_sync_signatures_provider_enabled", "provider_name", "enabled"),
        Index("ix_job_sync_signatures_provider_completed", "provider_name", "last_completed_at"),
        Index(
            "ix_job_sync_signatures_provider_request",
            "provider_name",
            "provider_country",
            "provider_where",
            "query_text",
        ),
        Index("ix_job_sync_signatures_location_target", "job_location_target_id"),
        Index("ix_job_sync_signatures_location_mapping", "job_provider_location_mapping_id"),
        Index("ix_job_sync_signatures_status_enabled", "verification_status", "enabled"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider_name: Mapped[str] = mapped_column(String(120))
    provider_type: Mapped[str] = mapped_column(String(60))
    sync_kind: Mapped[str] = mapped_column(String(80))
    sync_key: Mapped[str] = mapped_column(Text)
    query_text: Mapped[str] = mapped_column(Text)
    query_kind: Mapped[str] = mapped_column(String(80), default="manual")
    job_location_target_id: Mapped[str | None] = mapped_column(ForeignKey("job_location_targets.id", ondelete="SET NULL"), nullable=True)
    job_provider_location_mapping_id: Mapped[str | None] = mapped_column(
        ForeignKey("job_provider_location_mappings.id", ondelete="SET NULL"),
        nullable=True,
    )
    provider_country: Mapped[str | None] = mapped_column(String(16), nullable=True)
    provider_where: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_location: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_location_key: Mapped[str | None] = mapped_column(String(240), nullable=True)
    results_per_page: Mapped[int] = mapped_column(Integer, default=50)
    max_pages: Mapped[int] = mapped_column(Integer, default=1)
    freshness_hours: Mapped[int] = mapped_column(Integer, default=24)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    verification_status: Mapped[str] = mapped_column(String(40), default="verified")
    source: Mapped[str] = mapped_column(String(80), default="cli")
    created_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_raw_result_count: Mapped[int] = mapped_column(Integer, default=0)
    last_normalized_count: Mapped[int] = mapped_column(Integer, default=0)
    last_created_count: Mapped[int] = mapped_column(Integer, default=0)
    last_updated_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    criteria_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    job_location_target: Mapped[JobLocationTarget | None] = relationship()
    job_provider_location_mapping: Mapped[JobProviderLocationMapping | None] = relationship()


class JobSyncRun(Base, TimestampMixin):
    __tablename__ = "job_sync_runs"
    __table_args__ = (
        Index("ix_job_sync_runs_sync_key_completed", "sync_key", "completed_at"),
        Index("ix_job_sync_runs_provider_completed", "provider_name", "completed_at"),
        Index("ix_job_sync_runs_status_started", "status", "started_at"),
        Index("ix_job_sync_runs_ats_board_completed", "ats_provider", "ats_board_token", "completed_at"),
        Index("ix_job_sync_runs_signature", "job_sync_signature_id"),
        Index(
            "ix_job_sync_runs_provider_request_completed",
            "provider_name",
            "provider_country",
            "provider_where",
            "query_text",
            "completed_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_sync_signature_id: Mapped[str | None] = mapped_column(ForeignKey("job_sync_signatures.id", ondelete="SET NULL"), nullable=True)
    sync_key: Mapped[str] = mapped_column(Text)
    provider_name: Mapped[str] = mapped_column(String(120))
    provider_type: Mapped[str] = mapped_column(String(60))
    sync_kind: Mapped[str] = mapped_column(String(80))
    company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), nullable=True)
    company_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    ats_provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    ats_board_token: Mapped[str | None] = mapped_column(String(240), nullable=True)
    provider_country: Mapped[str | None] = mapped_column(String(16), nullable=True)
    target_country: Mapped[str | None] = mapped_column(String(80), nullable=True)
    target_location_kind: Mapped[str | None] = mapped_column(String(80), nullable=True)
    display_location: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_where: Mapped[str | None] = mapped_column(Text, nullable=True)
    query_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    query_kind: Mapped[str | None] = mapped_column(String(80), nullable=True)
    criteria_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(40), default="started")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_result_count: Mapped[int] = mapped_column(Integer, default=0)
    normalized_count: Mapped[int] = mapped_column(Integer, default=0)
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    closed_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_normalization_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    company: Mapped[Company | None] = relationship()
    job_sync_signature: Mapped[JobSyncSignature | None] = relationship()


class JobSearchRun(Base):
    __tablename__ = "job_search_runs"
    __table_args__ = (
        Index("ix_job_search_runs_profile_created", "candidate_profile_id", "created_at"),
        Index("ix_job_search_runs_profile_status_created", "candidate_profile_id", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"))
    command_text: Mapped[str] = mapped_column(Text)
    search_plan_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    run_diagnostics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    provider_names: Mapped[list[str]] = mapped_column(JSON, default=list)
    search_mode: Mapped[str | None] = mapped_column(String(60), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="started")
    total_provider_results: Mapped[int] = mapped_column(Integer, default=0)
    total_matches_reported: Mapped[int | None] = mapped_column(Integer, nullable=True)
    candidate_pool_count: Mapped[int] = mapped_column(Integer, default=0)
    candidate_count_after_dedupe: Mapped[int] = mapped_column(Integer, default=0)
    replans_attempted: Mapped[int] = mapped_column(Integer, default=0)
    model_selected_count: Mapped[int] = mapped_column(Integer, default=0)
    saved_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_existing_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    provider_error_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    candidate_profile: Mapped[CandidateProfile] = relationship(back_populates="job_search_runs")
    query_runs: Mapped[list[JobSearchQueryRun]] = relationship(back_populates="job_search_run", cascade="all, delete-orphan")


class JobSearchQueryRun(Base):
    __tablename__ = "job_search_query_runs"
    __table_args__ = (
        Index("ix_job_search_query_runs_run_created", "job_search_run_id", "created_at"),
        Index("ix_job_search_query_runs_provider", "provider_name", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_search_run_id: Mapped[str] = mapped_column(ForeignKey("job_search_runs.id", ondelete="CASCADE"))
    provider_name: Mapped[str] = mapped_column(String(120))
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    location: Mapped[str | None] = mapped_column(String(240), nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_matches: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_result_count: Mapped[int] = mapped_column(Integer, default=0)
    normalized_result_count: Mapped[int] = mapped_column(Integer, default=0)
    deduped_result_count: Mapped[int] = mapped_column(Integer, default=0)
    candidate_count_after_filters: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    job_search_run: Mapped[JobSearchRun] = relationship(back_populates="query_runs")


class JobRole(Base, TimestampMixin):
    __tablename__ = "job_roles"
    __table_args__ = (
        Index("ix_job_roles_profile_status", "candidate_profile_id", "status"),
        Index("ix_job_roles_company_title", "company_id", "title"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"))
    company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(240))
    job_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(240), nullable=True)
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="saved")
    raw_description_artifact_uri: Mapped[str | None] = mapped_column(Text, nullable=True)

    company: Mapped[Company | None] = relationship(back_populates="job_roles")
    applications: Mapped[list[Application]] = relationship(back_populates="job_role")


class Application(Base, TimestampMixin):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("candidate_profile_id", "job_id", name="uq_applications_profile_job"),
        Index("ix_applications_profile_status", "candidate_profile_id", "status"),
        Index("ix_applications_next_follow_up", "candidate_profile_id", "next_follow_up_date"),
        Index("ix_applications_profile_created", "candidate_profile_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"))
    company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), nullable=True)
    job_role_id: Mapped[str | None] = mapped_column(ForeignKey("job_roles.id", ondelete="SET NULL"), nullable=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("job_postings.id", ondelete="SET NULL"), nullable=True)
    saved_job_id: Mapped[str | None] = mapped_column(ForeignKey("candidate_saved_jobs.id", ondelete="SET NULL"), nullable=True)
    company_name: Mapped[str] = mapped_column(String(240))
    job_title: Mapped[str] = mapped_column(String(240))
    job_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(240), nullable=True)
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    date_applied: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="saved")
    notes: Mapped[str] = mapped_column(Text, default="")
    next_follow_up_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    archived_by_action: Mapped[str | None] = mapped_column(String(120), nullable=True)

    candidate_profile: Mapped[CandidateProfile] = relationship(back_populates="applications")
    company: Mapped[Company | None] = relationship(back_populates="applications")
    job_role: Mapped[JobRole | None] = relationship(back_populates="applications")
    job: Mapped[JobPosting | None] = relationship(back_populates="applications")
    saved_job: Mapped[CandidateSavedJob | None] = relationship(back_populates="applications")
    events: Mapped[list[ApplicationEvent]] = relationship(back_populates="application", cascade="all, delete-orphan")
    material_bundles: Mapped[list[ApplicationMaterialBundle]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="ApplicationMaterialBundle.created_at.desc()",
    )

    @property
    def source_provider(self) -> str | None:
        return self.job.source_provider if self.job is not None else None

    @property
    def posting_date(self) -> date | None:
        return self.job.posting_date if self.job is not None else None

    @property
    def fit_summary(self) -> str | None:
        return self.saved_job.fit_summary if self.saved_job is not None else None

    @property
    def salary_text(self) -> str | None:
        return self.job.salary_text if self.job is not None else None

    @property
    def remote_work_mode(self) -> str | None:
        return self.job.remote_work_mode if self.job is not None else None

    @property
    def employment_type(self) -> str | None:
        return self.job.employment_type if self.job is not None else None

    @property
    def apply_url(self) -> str | None:
        return self.job.apply_url if self.job is not None else None

    @property
    def latest_material_bundle(self) -> ApplicationMaterialBundle | None:
        return self.material_bundles[0] if self.material_bundles else None


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


class ApplicationMaterialBundle(Base, TimestampMixin):
    __tablename__ = "application_material_bundles"
    __table_args__ = (
        Index("ix_application_material_bundles_application_created", "application_id", "created_at"),
        Index("ix_application_material_bundles_profile_created", "candidate_profile_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    candidate_profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(40), default="generated")
    source_context_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    model_provider: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(240), nullable=True)

    application: Mapped[Application] = relationship(back_populates="material_bundles")
    candidate_profile: Mapped[CandidateProfile] = relationship(back_populates="application_material_bundles")
    items: Mapped[list[ApplicationMaterialItem]] = relationship(
        back_populates="bundle",
        cascade="all, delete-orphan",
        order_by="ApplicationMaterialItem.sort_order.asc()",
    )


class ApplicationMaterialItem(Base, TimestampMixin):
    __tablename__ = "application_material_items"
    __table_args__ = (
        Index("ix_application_material_items_bundle_sort", "bundle_id", "sort_order"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    bundle_id: Mapped[str] = mapped_column(ForeignKey("application_material_bundles.id", ondelete="CASCADE"))
    material_type: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(240))
    content: Mapped[str] = mapped_column(Text)
    content_format: Mapped[str] = mapped_column(String(40), default="markdown")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    bundle: Mapped[ApplicationMaterialBundle] = relationship(back_populates="items")


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
    __table_args__ = (
        Index("ix_profile_fact_drafts_session_created", "profile_intake_session_id", "created_at"),
        Index("ix_profile_fact_drafts_profile_review", "candidate_profile_id", "review_status"),
    )

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
        Index("ix_skill_claims_session_created", "profile_intake_session_id", "created_at"),
        Index(
            "ix_skill_claims_profile_publication",
            "candidate_profile_id",
            "publication_status",
            "verification_status",
            "visibility",
            "skill_category",
            "skill_name",
        ),
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
    __table_args__ = (
        Index("ix_resume_artifacts_profile_created", "candidate_profile_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(255))
    storage_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_status: Mapped[str] = mapped_column(String(40), default="pending")
    parsed_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProfileIntakeSession(Base, TimestampMixin):
    __tablename__ = "profile_intake_sessions"
    __table_args__ = (
        Index("ix_profile_intake_sessions_profile_status_created", "candidate_profile_id", "status", "created_at"),
        Index("ix_profile_intake_sessions_profile_turn_created", "candidate_profile_id", "last_turn_at", "created_at"),
    )

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
        Index("ix_profile_intake_events_profile_created", "candidate_profile_id", "created_at"),
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
        Index("ix_exp_project_drafts_session_created", "profile_intake_session_id", "created_at"),
        Index("ix_exp_project_drafts_profile_publication", "candidate_profile_id", "publication_status", "visibility", "created_at"),
        Index("ix_exp_project_drafts_profile_review", "candidate_profile_id", "review_status", "created_at"),
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
    __table_args__ = (
        Index("ix_evidence_artifacts_session_created", "profile_intake_session_id", "created_at"),
        Index("ix_evidence_artifacts_profile_publication", "candidate_profile_id", "publication_status", "visibility", "created_at"),
        Index("ix_evidence_artifacts_profile_review", "candidate_profile_id", "review_status", "created_at"),
    )

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
        Index("ix_usage_events_profile_created", "candidate_profile_id", "created_at"),
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
        Index("ix_command_interaction_logs_profile_created", "candidate_profile_id", "created_at"),
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
