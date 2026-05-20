"""Add persisted username identity.

Revision ID: 20260519_0007
Revises: 20260519_0006
Create Date: 2026-05-19
"""

from __future__ import annotations

import re

import sqlalchemy as sa
from alembic import context
from alembic import op


revision = "20260519_0007"
down_revision = "20260519_0006"
branch_labels = None
depends_on = None


USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,39}$")


def upgrade() -> None:
    op.add_column("users", sa.Column("username", sa.String(length=40), nullable=True))
    op.add_column("invite_tokens", sa.Column("username", sa.String(length=40), nullable=True))

    if not context.is_offline_mode():
        bind = op.get_bind()
        used_usernames: set[str] = set()
        users = bind.execute(sa.text("select id, email, display_name from users order by created_at, id")).mappings().all()
        for user in users:
            username = unique_username(candidate_username(user["email"], user["display_name"]), used_usernames)
            used_usernames.add(username)
            bind.execute(sa.text("update users set username = :username where id = :id"), {"username": username, "id": user["id"]})

        used_invite_usernames = set(used_usernames)
        invites = bind.execute(sa.text("select id, email, display_name, workspace_slug from invite_tokens order by created_at, id")).mappings().all()
        for invite in invites:
            username = unique_username(
                candidate_username(invite["workspace_slug"] or invite["email"], invite["display_name"]),
                used_invite_usernames,
            )
            used_invite_usernames.add(username)
            bind.execute(sa.text("update invite_tokens set username = :username where id = :id"), {"username": username, "id": invite["id"]})

    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("username", existing_type=sa.String(length=40), nullable=False)
    with op.batch_alter_table("invite_tokens") as batch_op:
        batch_op.alter_column("username", existing_type=sa.String(length=40), nullable=False)

    op.create_index("ix_users_username", "users", ["username"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_username", table_name="users")
    op.drop_column("invite_tokens", "username")
    op.drop_column("users", "username")


def candidate_username(primary: str | None, fallback: str | None) -> str:
    raw = (primary or fallback or "alpha-user").split("@", 1)[0]
    normalized = re.sub(r"[^a-z0-9_-]+", "-", raw.strip().casefold()).strip("-_")
    if not normalized or not normalized[0].isalnum():
        normalized = f"user-{normalized}".strip("-_")
    if len(normalized) < 3:
        normalized = f"{normalized}-user"
    normalized = normalized[:40].strip("-_")
    return normalized if USERNAME_RE.fullmatch(normalized) else "alpha-user"


def unique_username(base: str, used: set[str]) -> str:
    candidate = base[:40].strip("-_") or "alpha-user"
    suffix = 2
    while candidate in used:
        suffix_text = f"-{suffix}"
        candidate = f"{base[: 40 - len(suffix_text)].strip('-_')}{suffix_text}"
        suffix += 1
    return candidate
