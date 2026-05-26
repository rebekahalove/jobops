from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlalchemy import create_engine

from jobops_api.auth import (
    SESSION_COOKIE_NAME,
    create_or_rotate_alpha_invitation,
    create_session_for_username,
    hash_token,
    now_utc,
    seed_initial_user,
)
from jobops_api.db.models import AlphaAccessRequest, AlphaInvitation, Base, PasswordResetToken, User, UserSession
from jobops_api.db.session import get_db_session
from jobops_api.main import app
from jobops_api.security import INTERNAL_API_KEY_HEADER


INTERNAL_HEADERS = {INTERNAL_API_KEY_HEADER: "test-secret"}


def test_admin_routes_require_admin_user(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    engine = make_engine()
    admin_cookie, user_cookie = seed_admin_and_user(engine)

    with app_with_session(engine):
        client = TestClient(app)
        assert client.get("/v1/admin/users", headers=INTERNAL_HEADERS).status_code == 401
        assert client.get("/v1/admin/users", headers=INTERNAL_HEADERS, cookies={SESSION_COOKIE_NAME: user_cookie}).status_code == 403
        response = client.get("/v1/admin/users", headers=INTERNAL_HEADERS, cookies={SESSION_COOKIE_NAME: admin_cookie})
        assert response.status_code == 200
        assert response.json()["result"]["users"][0]["userType"] == "admin"


def test_pending_alpha_requests_are_oldest_first_and_invitable(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    engine = make_engine()
    admin_cookie, _ = seed_admin_and_user(engine)
    older_at = now_utc() - timedelta(days=2)
    newer_at = now_utc() - timedelta(days=1)

    with Session(engine) as session:
        older = AlphaAccessRequest(name="Older", email="older@example.com", note="old", created_at=older_at)
        newer = AlphaAccessRequest(name="Newer", email="newer@example.com", note="new", created_at=newer_at)
        invited = AlphaAccessRequest(name="Invited", email="invited@example.com", note="", status="invited", created_at=older_at)
        session.add_all([newer, older, invited])
        session.commit()
        older_id = older.id

    with app_with_session(engine):
        client = TestClient(app)
        listed = client.get("/v1/admin/alpha-requests", headers=INTERNAL_HEADERS, cookies={SESSION_COOKIE_NAME: admin_cookie})
        assert listed.status_code == 200
        assert [item["email"] for item in listed.json()["result"]["requests"]] == ["older@example.com", "newer@example.com"]

        invited_response = client.post(
            f"/v1/admin/alpha-requests/{older_id}/invite",
            headers=INTERNAL_HEADERS,
            cookies={SESSION_COOKIE_NAME: admin_cookie},
            json={},
        )
        assert invited_response.status_code == 201

    with Session(engine) as session:
        stored = session.get(AlphaAccessRequest, older_id)
        assert stored is not None
        assert stored.status == "invited"
        assert stored.invited_at is not None
        assert stored.invitation_id is not None


def test_manual_invite_updates_matching_request_and_deduplicates_pending_invites(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    engine = make_engine()
    admin_cookie, _ = seed_admin_and_user(engine)

    with Session(engine) as session:
        request = AlphaAccessRequest(name="Casey", email="casey@example.com", note="")
        session.add(request)
        session.commit()
        request_id = request.id

    with app_with_session(engine):
        client = TestClient(app)
        first = client.post(
            "/v1/admin/invitations",
            headers=INTERNAL_HEADERS,
            cookies={SESSION_COOKIE_NAME: admin_cookie},
            json={"email": "CASEY@example.com"},
        )
        second = client.post(
            "/v1/admin/invitations",
            headers=INTERNAL_HEADERS,
            cookies={SESSION_COOKIE_NAME: admin_cookie},
            json={"email": "casey@example.com"},
        )
        assert first.status_code == 201
        assert second.status_code == 201
        assert second.json()["result"]["rotatedExisting"] is True

    with Session(engine) as session:
        assert session.scalar(select(AlphaInvitation).where(AlphaInvitation.email == "casey@example.com")).email == "casey@example.com"
        assert len(list(session.scalars(select(AlphaInvitation).where(AlphaInvitation.email == "casey@example.com")))) == 1
        stored_request = session.get(AlphaAccessRequest, request_id)
        assert stored_request is not None
        assert stored_request.status == "invited"
        assert stored_request.invited_at is not None
        assert stored_request.invitation_id is not None


def test_invitation_token_is_hashed_and_cannot_be_reused(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    engine = make_engine()

    with Session(engine) as session:
        created = create_or_rotate_alpha_invitation(session, email="invitee@example.com", invited_by_user_id=None)
        raw_token = created.raw_token
        expired = AlphaInvitation(
            email="expired@example.com",
            token_hash=hash_token("expired-token-with-enough-length"),
            status="pending",
            expires_at=now_utc() - timedelta(minutes=1),
        )
        session.add(expired)
        session.commit()
        assert created.invitation.token_hash != raw_token

    with app_with_session(engine):
        client = TestClient(app)
        accepted = client.post(
            "/v1/invitations/accept",
            headers=INTERNAL_HEADERS,
            json={
                "token": raw_token,
                "username": "invitee-user",
                "display_name": "Invitee User",
                "password": "invitee secure password",
            },
        )
        assert accepted.status_code == 200
        replay = client.post(
            "/v1/invitations/accept",
            headers=INTERNAL_HEADERS,
            json={
                "token": raw_token,
                "username": "invitee-user",
                "display_name": "Invitee User",
                "password": "invitee secure password",
            },
        )
        assert replay.status_code == 404
        expired_response = client.post(
            "/v1/invitations/accept",
            headers=INTERNAL_HEADERS,
            json={
                "token": "expired-token-with-enough-length",
                "username": "expired-user",
                "display_name": "Expired User",
                "password": "expired secure password",
            },
        )
        assert expired_response.status_code == 410

    with Session(engine) as session:
        invitation = session.scalar(select(AlphaInvitation).where(AlphaInvitation.email == "invitee@example.com"))
        assert invitation is not None
        assert invitation.status == "accepted"
        assert invitation.accepted_at is not None
        user = session.scalar(select(User).where(User.email == "invitee@example.com"))
        assert user is not None
        assert user.user_type == "user"


def test_accepting_invite_does_not_demote_existing_admin(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    engine = make_engine()

    with Session(engine) as session:
        seed_initial_user(
            session,
            email="admin@example.com",
            username="admin-user",
            display_name="Admin User",
            password="admin secure password",
            password_reset_required=False,
            user_type="admin",
        )
        created = create_or_rotate_alpha_invitation(session, email="admin@example.com", invited_by_user_id=None)
        raw_token = created.raw_token
        session.commit()

    with app_with_session(engine):
        response = TestClient(app).post(
            "/v1/invitations/accept",
            headers=INTERNAL_HEADERS,
            json={
                "token": raw_token,
                "username": "admin-user",
                "display_name": "Admin User",
                "password": "admin secure replacement",
            },
        )
        assert response.status_code == 200

    with Session(engine) as session:
        user = session.scalar(select(User).where(User.email == "admin@example.com"))
        assert user is not None
        assert user.user_type == "admin"


def test_admin_cannot_demote_or_delete_self_or_last_admin(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    engine = make_engine()
    admin_cookie, _ = seed_admin_and_user(engine)

    with Session(engine) as session:
        admin = session.scalar(select(User).where(User.email == "admin@example.com"))
        user = session.scalar(select(User).where(User.email == "user@example.com"))
        assert admin is not None and user is not None
        admin_id = admin.id
        user_id = user.id

    with app_with_session(engine):
        client = TestClient(app)
        self_demote = client.patch(
            f"/v1/admin/users/{admin_id}/role",
            headers=INTERNAL_HEADERS,
            cookies={SESSION_COOKIE_NAME: admin_cookie},
            json={"user_type": "user"},
        )
        self_delete = client.delete(
            f"/v1/admin/users/{admin_id}",
            headers=INTERNAL_HEADERS,
            cookies={SESSION_COOKIE_NAME: admin_cookie},
        )
        promote_user = client.patch(
            f"/v1/admin/users/{user_id}/role",
            headers=INTERNAL_HEADERS,
            cookies={SESSION_COOKIE_NAME: admin_cookie},
            json={"user_type": "admin"},
        )
        demote_user = client.patch(
            f"/v1/admin/users/{user_id}/role",
            headers=INTERNAL_HEADERS,
            cookies={SESSION_COOKIE_NAME: admin_cookie},
            json={"user_type": "user"},
        )
        assert self_demote.status_code == 400
        assert self_delete.status_code == 400
        assert promote_user.status_code == 200
        assert demote_user.status_code == 200


def test_admin_delete_blocks_last_admin_and_password_expire_creates_reset(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JOBOPS_INTERNAL_API_KEY", "test-secret")
    engine = make_engine()
    admin_cookie, _ = seed_admin_and_user(engine)

    with Session(engine) as session:
        admin = session.scalar(select(User).where(User.email == "admin@example.com"))
        user = session.scalar(select(User).where(User.email == "user@example.com"))
        assert admin is not None and user is not None
        admin_id = admin.id
        user_id = user.id

    with app_with_session(engine):
        client = TestClient(app)
        reset = client.post(
            f"/v1/admin/users/{user_id}/expire-password",
            headers=INTERNAL_HEADERS,
            cookies={SESSION_COOKIE_NAME: admin_cookie},
        )
        deleted_user = client.delete(
            f"/v1/admin/users/{user_id}",
            headers=INTERNAL_HEADERS,
            cookies={SESSION_COOKIE_NAME: admin_cookie},
        )
        assert reset.status_code == 200
        assert deleted_user.status_code == 200

    with Session(engine) as session:
        user = session.get(User, user_id)
        assert user is not None
        assert user.status == "deleted"
        assert user.password_hash is None
        assert session.scalar(select(PasswordResetToken)) is not None
        assert session.scalar(select(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))) is None
        admin = session.get(User, admin_id)
        assert admin is not None
        assert admin.user_type == "admin"


def test_seed_initial_user_can_create_admin_only_when_explicit() -> None:
    engine = make_engine()
    with Session(engine) as session:
        normal = seed_initial_user(
            session,
            email="normal@example.com",
            username="normal-user",
            display_name="Normal User",
            password="normal secure password",
            password_reset_required=False,
        )
        admin = seed_initial_user(
            session,
            email="seed-admin@example.com",
            username="seed-admin",
            display_name="Seed Admin",
            password="admin secure password",
            password_reset_required=False,
            user_type="admin",
        )
        session.commit()
        assert normal.user.user_type == "user"
        assert admin.user.user_type == "admin"


def make_engine():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine


def seed_admin_and_user(engine) -> tuple[str, str]:
    with Session(engine) as session:
        seed_initial_user(
            session,
            email="admin@example.com",
            username="admin-user",
            display_name="Admin User",
            password="admin secure password",
            password_reset_required=False,
            user_type="admin",
        )
        seed_initial_user(
            session,
            email="user@example.com",
            username="normal-user",
            display_name="Normal User",
            password="normal secure password",
            password_reset_required=False,
        )
        _, admin_cookie = create_session_for_username(session, username="admin-user", password="admin secure password")
        _, user_cookie = create_session_for_username(session, username="normal-user", password="normal secure password")
        session.commit()
        return admin_cookie, user_cookie


class app_with_session:
    def __init__(self, engine) -> None:
        self.engine = engine

    def __enter__(self):
        def override_session() -> Iterator[Session]:
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[get_db_session] = override_session
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        app.dependency_overrides.clear()
