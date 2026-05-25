from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from jobops_api.db.models import CandidateProfile, ProfileFieldValue


FieldGroup = Literal["profile_basics", "targets"]
Visibility = Literal["private", "public"]


@dataclass(frozen=True)
class ProfileFieldDefinition:
    group: FieldGroup
    name: str
    label: str
    public_allowed: bool
    multiline: bool = False
    private_only: bool = False


PROFILE_FIELD_DEFINITIONS: tuple[ProfileFieldDefinition, ...] = (
    ProfileFieldDefinition("profile_basics", "displayName", "Display name", True),
    ProfileFieldDefinition("profile_basics", "headline", "Headline", True),
    ProfileFieldDefinition("profile_basics", "summary", "Summary", True, multiline=True),
    ProfileFieldDefinition("profile_basics", "emailAddress", "Email address", True),
    ProfileFieldDefinition("profile_basics", "telephoneNumber", "Telephone number", True),
    ProfileFieldDefinition("profile_basics", "calendlyLink", "Calendly link", True),
    ProfileFieldDefinition("profile_basics", "currentLocation", "Current location", True),
    ProfileFieldDefinition("profile_basics", "mailingAddress", "Mailing address", False, multiline=True, private_only=True),
    ProfileFieldDefinition("targets", "targetTitles", "Target titles", True),
    ProfileFieldDefinition("targets", "roleFamilies", "Target role families", True),
    ProfileFieldDefinition("targets", "preferredWorkMode", "Preferred work mode", True),
    ProfileFieldDefinition("targets", "preferredLocations", "Preferred locations", True),
    ProfileFieldDefinition("targets", "domainsOrIndustries", "Domains or industries of interest", True),
    ProfileFieldDefinition("targets", "constraints", "Constraints / dealbreakers", True, multiline=True),
    ProfileFieldDefinition("targets", "compensationMin", "Compensation min", False, private_only=True),
)


PROFILE_FIELD_MAP = {(field.group, field.name): field for field in PROFILE_FIELD_DEFINITIONS}


def get_field_definition(group: str, field_name: str) -> ProfileFieldDefinition:
    definition = PROFILE_FIELD_MAP.get((group, field_name))
    if definition is None:
        raise HTTPException(status_code=404, detail="Profile field not found.")
    return definition


def public_field_names(group: FieldGroup) -> set[str]:
    return {field.name for field in PROFILE_FIELD_DEFINITIONS if field.group == group and field.public_allowed}


def field_value_rows(session: Session, candidate_profile_id: str, *, group: FieldGroup | None = None) -> list[ProfileFieldValue]:
    statement = select(ProfileFieldValue).where(ProfileFieldValue.candidate_profile_id == candidate_profile_id)
    if group is not None:
        statement = statement.where(ProfileFieldValue.field_group == group)
    return list(session.scalars(statement.order_by(ProfileFieldValue.created_at.asc())))


def latest_field_row(
    session: Session,
    candidate_profile_id: str,
    group: FieldGroup,
    field_name: str,
    lifecycle_status: Literal["generated", "published", "archived"],
    *,
    visibility: Visibility | None = None,
) -> ProfileFieldValue | None:
    statement = select(ProfileFieldValue).where(
        ProfileFieldValue.candidate_profile_id == candidate_profile_id,
        ProfileFieldValue.field_group == group,
        ProfileFieldValue.field_name == field_name,
        ProfileFieldValue.lifecycle_status == lifecycle_status,
    )
    if visibility is not None:
        statement = statement.where(ProfileFieldValue.visibility == visibility)
    return session.scalar(statement.order_by(ProfileFieldValue.updated_at.desc(), ProfileFieldValue.created_at.desc()).limit(1))


def latest_published_field(
    session: Session,
    candidate_profile_id: str,
    group: FieldGroup,
    field_name: str,
) -> ProfileFieldValue | None:
    return latest_field_row(session, candidate_profile_id, group, field_name, "published")


def ensure_generated_field(
    session: Session,
    profile: CandidateProfile,
    definition: ProfileFieldDefinition,
    value: str,
    *,
    source: str = "user",
) -> ProfileFieldValue:
    row = latest_field_row(session, profile.id, definition.group, definition.name, "generated")
    if row is None:
        row = ProfileFieldValue(
            candidate_profile_id=profile.id,
            field_group=definition.group,
            field_name=definition.name,
            value_text=value,
            source=source,
            lifecycle_status="generated",
            visibility=None,
            original_value_text=value,
            field_metadata={},
        )
        session.add(row)
        session.flush()
        return row
    row.value_text = value
    row.source = source
    return row


def update_published_field(row: ProfileFieldValue, value: str) -> None:
    if row.lifecycle_status != "published":
        raise HTTPException(status_code=400, detail="Only published fields can be updated here.")
    row.value_text = value


def publish_generated_field(
    session: Session,
    profile: CandidateProfile,
    row: ProfileFieldValue,
    definition: ProfileFieldDefinition,
    visibility: Visibility,
) -> ProfileFieldValue:
    if row.lifecycle_status != "generated":
        raise HTTPException(status_code=400, detail="Only generated fields can be published.")
    require_visibility_allowed(definition, visibility)
    previous = latest_published_field(session, profile.id, definition.group, definition.name)
    if previous is not None:
        archive_field_value(previous, reason="replaced")
    row.lifecycle_status = "published"
    row.visibility = visibility
    row.published_at = datetime.now(UTC)
    row.archive_reason = None
    sync_profile_shell_field(profile, definition, row.value_text, visibility)
    return row


def change_published_field_visibility(row: ProfileFieldValue, definition: ProfileFieldDefinition, visibility: Visibility) -> None:
    if row.lifecycle_status != "published":
        raise HTTPException(status_code=400, detail="Only published fields can change visibility.")
    require_visibility_allowed(definition, visibility)
    row.visibility = visibility


def archive_field_value(row: ProfileFieldValue, *, reason: str = "dismissed") -> None:
    row.lifecycle_status = "archived"
    row.visibility = None
    row.archive_reason = reason
    row.archived_at = datetime.now(UTC)


def require_visibility_allowed(definition: ProfileFieldDefinition, visibility: Visibility) -> None:
    if visibility == "public" and not definition.public_allowed:
        raise HTTPException(status_code=400, detail="This field cannot be public.")


def sync_profile_shell_field(profile: CandidateProfile, definition: ProfileFieldDefinition, value: str, visibility: Visibility) -> None:
    if definition.group == "profile_basics":
        if definition.name == "displayName":
            profile.display_name = value
        elif definition.name == "headline":
            profile.headline = value
        elif definition.name == "summary":
            profile.summary = value


def field_rows_snapshot(session: Session, profile: CandidateProfile) -> dict[str, Any]:
    rows = field_value_rows(session, profile.id)
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for definition in PROFILE_FIELD_DEFINITIONS:
        grouped[(definition.group, definition.name)] = {
            "group": definition.group,
            "name": definition.name,
            "label": definition.label,
            "publicAllowed": definition.public_allowed,
            "privateOnly": definition.private_only,
            "multiline": definition.multiline,
            "generated": None,
            "published": None,
            "archived": [],
        }

    for row in rows:
        key = (row.field_group, row.field_name)
        if key not in grouped:
            continue
        payload = serialize_field_row(row)
        if row.lifecycle_status == "generated":
            grouped[key]["generated"] = payload
        elif row.lifecycle_status == "published":
            grouped[key]["published"] = payload
        elif row.lifecycle_status == "archived":
            grouped[key]["archived"].append(payload)

    return {
        "profileBasics": [value for key, value in grouped.items() if key[0] == "profile_basics"],
        "targets": [value for key, value in grouped.items() if key[0] == "targets"],
    }


def serialize_field_row(row: ProfileFieldValue) -> dict[str, Any]:
    return {
        "id": row.id,
        "value": row.value_text,
        "source": row.source,
        "lifecycleStatus": row.lifecycle_status,
        "visibility": row.visibility,
        "archiveReason": row.archive_reason,
        "originalValue": row.original_value_text,
    }


def published_field_values(
    session: Session,
    candidate_profile_id: str,
    group: FieldGroup,
    *,
    visibility: Visibility | None = None,
    public_only: bool = False,
) -> dict[str, str]:
    values: dict[str, str] = {}
    names = public_field_names(group) if public_only else {field.name for field in PROFILE_FIELD_DEFINITIONS if field.group == group}
    for row in field_value_rows(session, candidate_profile_id, group=group):
        if row.lifecycle_status != "published" or row.field_name not in names:
            continue
        if visibility is not None and row.visibility != visibility:
            continue
        values[row.field_name] = row.value_text
    return values


def published_field_group_visibility(
    session: Session,
    candidate_profile_id: str,
    group: FieldGroup,
) -> Visibility | None:
    visibility: Visibility | None = None
    names = {field.name for field in PROFILE_FIELD_DEFINITIONS if field.group == group}
    for row in field_value_rows(session, candidate_profile_id, group=group):
        if row.lifecycle_status != "published" or row.field_name not in names:
            continue
        if row.visibility == "private":
            return "private"
        if row.visibility == "public":
            visibility = "public"
    return visibility


def private_context_field_items(session: Session, profile: CandidateProfile) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    published: list[dict[str, Any]] = []
    generated: list[dict[str, Any]] = []
    archived: list[dict[str, Any]] = []
    for row in field_value_rows(session, profile.id):
        item = {
            "type": "profile-field",
            "group": row.field_group,
            "field": row.field_name,
            "value": row.value_text,
            "visibility": row.visibility,
            "state": row.lifecycle_status,
        }
        if row.lifecycle_status == "published":
            published.append(item)
        elif row.lifecycle_status == "generated":
            generated.append(item)
        elif row.lifecycle_status == "archived":
            archived.append({**item, "archiveReason": row.archive_reason})
    return published, generated, archived
