from __future__ import annotations

import argparse
import getpass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from jobops_api.auth import USER_TYPE_ADMIN, USER_TYPE_USER, create_alpha_invite, normalize_email, normalize_user_type, seed_initial_user
from jobops_api.db.models import Application, ApplicationEvent, CandidateProfile, CommandInteractionLog, JobRole, TargetCompany, Tenant, User, UserSession, WorkspaceMembership
from jobops_api.db.seed_profile import seed_public_profile
from jobops_api.db.session import create_db_engine
from jobops_api.profile_seed import load_public_seed_profile


def main() -> None:
    parser = argparse.ArgumentParser(prog="jobops-api")
    subparsers = parser.add_subparsers(dest="command", required=True)

    seed_parser = subparsers.add_parser(
        "seed-public-profile",
        help="Seed the approved public candidate profile shell into the configured database.",
    )
    seed_parser.add_argument(
        "--hostname",
        default=None,
        help="Optional public hostname to map to the seeded candidate profile.",
    )
    invite_parser = subparsers.add_parser("create-alpha-invite", help="Create a single-use alpha invite token.")
    invite_parser.add_argument("--email", required=True)
    invite_parser.add_argument("--name", default=None)
    invite_parser.add_argument("--workspace-slug", default=None)
    invite_parser.add_argument("--created-by", default="cli")

    bootstrap_parser = subparsers.add_parser("bootstrap-alpha-user", help="Create or repair a user/workspace/profile without issuing an invite.")
    bootstrap_parser.add_argument("--email", required=True)
    bootstrap_parser.add_argument("--username", required=True)
    bootstrap_parser.add_argument("--name", required=True)
    bootstrap_parser.add_argument("--password", default=None)
    bootstrap_parser.add_argument("--prompt-password", action="store_true")
    bootstrap_parser.add_argument("--require-reset", action=argparse.BooleanOptionalAction, default=True)
    bootstrap_parser.add_argument("--workspace-slug", default=None)
    bootstrap_parser.add_argument("--admin", action="store_true", help="Create or repair the user as an admin. Must be explicit.")
    bootstrap_parser.add_argument("--user-type", choices=[USER_TYPE_USER, USER_TYPE_ADMIN], default=USER_TYPE_USER, help="User type to assign. Defaults to user.")

    seed_user_parser = subparsers.add_parser("seed-initial-user", help="Seed the initial persisted alpha user/workspace/profile.")
    seed_user_parser.add_argument("--email", required=True)
    seed_user_parser.add_argument("--username", required=True)
    seed_user_parser.add_argument("--name", required=True)
    seed_user_parser.add_argument("--password", default=None)
    seed_user_parser.add_argument("--prompt-password", action="store_true")
    seed_user_parser.add_argument("--require-reset", action=argparse.BooleanOptionalAction, default=True)
    seed_user_parser.add_argument("--workspace-slug", default=None)
    seed_user_parser.add_argument("--admin", action="store_true", help="Create the user as an admin. Must be explicit; never defaults on.")
    seed_user_parser.add_argument("--user-type", choices=[USER_TYPE_USER, USER_TYPE_ADMIN], default=USER_TYPE_USER, help="User type to assign. Defaults to user.")
    seed_user_parser.add_argument("--update-existing", action="store_true", help="Allow updating an existing matching seed user instead of failing.")

    inspect_parser = subparsers.add_parser("inspect-alpha-workspaces", help="Print users, workspaces, and profile ids.")
    inspect_parser.add_argument("--workspace-slug", default=None)

    reset_parser = subparsers.add_parser("reset-test-workspace", help="Delete mutable test workspace data for a workspace slug.")
    reset_parser.add_argument("--workspace-slug", required=True)

    args = parser.parse_args()

    if args.command == "seed-public-profile":
        seed_public_profile_command(hostname=args.hostname)
    elif args.command == "create-alpha-invite":
        create_alpha_invite_command(
            email=args.email,
            name=args.name,
            workspace_slug=args.workspace_slug,
            created_by=args.created_by,
        )
    elif args.command == "bootstrap-alpha-user":
        seed_initial_user_command(
            email=args.email,
            username=args.username,
            name=args.name,
            password=resolve_password_arg(args.password, args.prompt_password),
            require_reset=args.require_reset,
            workspace_slug=args.workspace_slug,
            user_type=resolve_user_type_args(args.admin, args.user_type),
            update_existing=True,
        )
    elif args.command == "seed-initial-user":
        seed_initial_user_command(
            email=args.email,
            username=args.username,
            name=args.name,
            password=resolve_password_arg(args.password, args.prompt_password),
            require_reset=args.require_reset,
            workspace_slug=args.workspace_slug,
            user_type=resolve_user_type_args(args.admin, args.user_type),
            update_existing=args.update_existing,
        )
    elif args.command == "inspect-alpha-workspaces":
        inspect_alpha_workspaces_command(workspace_slug=args.workspace_slug)
    elif args.command == "reset-test-workspace":
        reset_test_workspace_command(workspace_slug=args.workspace_slug)


def seed_public_profile_command(hostname: str | None = None) -> None:
    profile = load_public_seed_profile()
    engine = create_db_engine()
    with Session(engine) as session:
        candidate_profile = seed_public_profile(session, profile, hostname=hostname)
        candidate_slug = candidate_profile.slug
        session.commit()

    print(f"Seeded candidate profile: {candidate_slug}")


def create_alpha_invite_command(*, email: str, name: str | None, workspace_slug: str | None, created_by: str | None) -> None:
    engine = create_db_engine()
    with Session(engine) as session:
        created = create_alpha_invite(
            session,
            email=email,
            display_name=name,
            workspace_slug=workspace_slug,
            created_by=created_by,
        )
        session.commit()
        print(f"Invite created for {created.invite.email}")
        print(f"Expires at: {created.invite.expires_at.isoformat() if created.invite.expires_at else 'never'}")
        print("Invite token was generated and stored hashed; it is not printed by the CLI.")


def seed_initial_user_command(
    *,
    email: str,
    username: str,
    name: str,
    password: str,
    require_reset: bool,
    workspace_slug: str | None,
    user_type: str = USER_TYPE_USER,
    update_existing: bool = False,
) -> None:
    engine = create_db_engine()
    with Session(engine) as session:
        normalized_email = normalize_email(email)
        existing = session.scalar(select(User).where((User.email == normalized_email) | (User.username == username.strip().casefold())))
        if existing is not None and not update_existing:
            raise SystemExit("User already exists. Re-run with --update-existing if you intend to repair this seed user.")
        auth = seed_initial_user(
            session,
            email=normalized_email,
            username=username,
            display_name=name,
            password=password,
            password_reset_required=require_reset,
            workspace_slug=workspace_slug,
            user_type=normalize_user_type(user_type),
        )
        session.commit()
        print(f"User: {auth.user.username} <{auth.user.email}> ({auth.user.id}) type={auth.user.user_type}")
        print(f"Workspace: {auth.tenant.slug} ({auth.tenant.id})")
        print(f"Candidate profile: {auth.candidate_profile.slug} ({auth.candidate_profile.id})")


def resolve_password_arg(password: str | None, prompt_password: bool) -> str:
    if password:
        return password
    if prompt_password:
        first = getpass.getpass("Password: ")
        second = getpass.getpass("Confirm password: ")
        if first != second:
            raise SystemExit("Passwords did not match.")
        return first
    raise SystemExit("Password is required. Pass --password or use --prompt-password.")


def resolve_user_type_args(admin: bool, user_type: str) -> str:
    if admin and user_type != USER_TYPE_USER:
        raise SystemExit("Use either --admin or --user-type admin, not both.")
    if admin:
        return USER_TYPE_ADMIN
    return normalize_user_type(user_type)


def inspect_alpha_workspaces_command(*, workspace_slug: str | None = None) -> None:
    engine = create_db_engine()
    with Session(engine) as session:
        statement = (
            select(User, Tenant, CandidateProfile, WorkspaceMembership)
            .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
            .join(Tenant, Tenant.id == WorkspaceMembership.tenant_id)
            .join(CandidateProfile, CandidateProfile.tenant_id == Tenant.id, isouter=True)
            .order_by(User.email.asc(), Tenant.slug.asc())
        )
        if workspace_slug:
            statement = statement.where(Tenant.slug == workspace_slug)
        for user, tenant, profile, membership in session.execute(statement):
            print(
                f"{user.username} <{user.email}> | workspace={tenant.slug} ({tenant.id}) | "
                f"profile={profile.slug if profile else '-'} ({profile.id if profile else '-'}) | role={membership.role}"
            )


def reset_test_workspace_command(*, workspace_slug: str) -> None:
    engine = create_db_engine()
    with Session(engine) as session:
        tenant = session.scalar(select(Tenant).where(Tenant.slug == workspace_slug))
        if tenant is None:
            raise SystemExit(f"Workspace not found: {workspace_slug}")
        profile_ids = list(session.scalars(select(CandidateProfile.id).where(CandidateProfile.tenant_id == tenant.id)))
        for profile_id in profile_ids:
            application_ids = list(session.scalars(select(Application.id).where(Application.candidate_profile_id == profile_id)))
            if application_ids:
                session.execute(delete(ApplicationEvent).where(ApplicationEvent.application_id.in_(application_ids)))
            session.execute(delete(Application).where(Application.candidate_profile_id == profile_id))
            session.execute(delete(JobRole).where(JobRole.candidate_profile_id == profile_id))
            session.execute(delete(TargetCompany).where(TargetCompany.candidate_profile_id == profile_id))
        session.execute(delete(CommandInteractionLog).where(CommandInteractionLog.tenant_id == tenant.id))
        session.execute(delete(UserSession).where(UserSession.tenant_id == tenant.id))
        session.commit()
        print(f"Reset mutable test data for workspace: {workspace_slug}")


if __name__ == "__main__":
    main()
