from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
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
    target_titles: Mapped[list[str]] = mapped_column(JSON, default=list)
    role_families: Mapped[list[str]] = mapped_column(JSON, default=list)
    seniority: Mapped[str | None] = mapped_column(String(80), nullable=True)
    preferred_locations: Mapped[list[str]] = mapped_column(JSON, default=list)
    work_modes: Mapped[list[str]] = mapped_column(JSON, default=list)
    constraints: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


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
    skill_name: Mapped[str] = mapped_column(String(160))
    skill_category: Mapped[str] = mapped_column(String(120))
    years_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    years_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recency: Mapped[str | None] = mapped_column(String(80), nullable=True)
    proficiency: Mapped[str | None] = mapped_column(String(80), nullable=True)
    evidence_fact_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    visibility: Mapped[str] = mapped_column(String(40), default="private")
    verification_status: Mapped[str] = mapped_column(String(40), default="draft")


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


class EvidenceArtifact(Base):
    __tablename__ = "evidence_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    candidate_profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"))
    artifact_type: Mapped[str] = mapped_column(String(80))
    label: Mapped[str] = mapped_column(String(255))
    uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    visibility: Mapped[str] = mapped_column(String(40), default="private")
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
