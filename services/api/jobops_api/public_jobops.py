from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db.models import (
    AlphaAccessRequest,
    Application,
    CommandInteractionLog,
    JobRole,
    ProfileFact,
    ProfileFactDraft,
    TargetCompany,
    User,
)
from .db.session import get_db_session
from .security import require_internal_api_key


router = APIRouter(
    prefix="/v1/public/jobops",
    tags=["public-jobops"],
    dependencies=[Depends(require_internal_api_key)],
)

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AlphaAccessRequestCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("name", mode="after")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return " ".join(value.strip().split())

    @field_validator("email", mode="after")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not EMAIL_PATTERN.match(normalized):
            raise ValueError("A valid email address is required.")
        return normalized

    @field_validator("note", mode="after")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


@router.get("/metrics")
def get_public_metrics(session: Session = Depends(get_db_session)) -> dict[str, Any]:
    metrics = [
        metric("alphaAccessRequests", "Alpha access requests", count_rows(session, AlphaAccessRequest)),
        metric("usersOnboarded", "Users onboarded", count_rows(session, User)),
        metric("companiesTracked", "Companies tracked", count_rows(session, TargetCompany)),
        metric("jobsTracked", "Jobs tracked", count_rows(session, JobRole)),
        metric("profileDraftsCreated", "Profile drafts created", count_rows(session, ProfileFactDraft)),
        metric(
            "profileDraftsPublished",
            "Profile drafts published",
            count_rows(
                session,
                ProfileFact,
                ProfileFact.visibility == "public",
                ProfileFact.verification_status == "published",
            ),
        ),
        metric("applicationsTracked", "Applications tracked", count_rows(session, Application)),
        metric(
            "aiAssistedActionsCompleted",
            "AI-assisted actions completed",
            count_rows(session, CommandInteractionLog, CommandInteractionLog.action_applied.is_(True)),
        ),
    ]

    return {
        "ok": True,
        "result": {
            "metrics": metrics,
            "updatedAt": datetime.now(UTC).isoformat(),
        },
    }


@router.post("/access-requests", status_code=201)
def create_access_request(
    request: AlphaAccessRequestCreate,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    access_request = AlphaAccessRequest(
        name=request.name,
        email=request.email,
        note=request.note or "",
    )
    session.add(access_request)
    session.commit()
    session.refresh(access_request)

    return {
        "ok": True,
        "result": {
            "requestId": access_request.id,
            "createdAt": access_request.created_at.isoformat(),
            "message": "Thanks for your interest. Your alpha access request was received.",
        },
    }


def metric(metric_id: str, label: str, value: int) -> dict[str, int | str]:
    return {
        "id": metric_id,
        "label": label,
        "value": value,
    }


def count_rows(session: Session, model: type[Any], *criteria: Any) -> int:
    statement = select(func.count()).select_from(model)
    if criteria:
        statement = statement.where(*criteria)
    return int(session.scalar(statement) or 0)
