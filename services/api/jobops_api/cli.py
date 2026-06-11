from __future__ import annotations

import argparse
import getpass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from jobops_api.auth import USER_TYPE_ADMIN, USER_TYPE_USER, create_alpha_invite, normalize_email, normalize_user_type, seed_initial_user
from jobops_api.db.models import (
    Application,
    ApplicationEvent,
    CandidateCompany,
    CandidateProfile,
    CommandInteractionLog,
    JobLocationTarget,
    JobProviderLocationMapping,
    JobRole,
    JobSyncSignature,
    Tenant,
    User,
    UserSession,
    WorkspaceMembership,
)
from jobops_api.db.seed_profile import seed_public_profile
from jobops_api.db.session import create_db_engine
from jobops_api.job_discovery.greenhouse_seed import upsert_greenhouse_companies_for_candidate
from jobops_api.job_discovery.job_sync.adzuna_service import sync_adzuna_signatures, upsert_adzuna_sync_signature
from jobops_api.job_discovery.job_sync.greenhouse_service import sync_greenhouse_boards
from jobops_api.job_discovery.job_sync.location_resolver import ensure_initial_job_location_mappings
from jobops_api.profile_seed import load_public_seed_profile
from jobops_api.settings import load_settings


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

    greenhouse_parser = subparsers.add_parser(
        "seed-greenhouse-companies",
        help="Upsert known Greenhouse-backed companies for a candidate profile.",
    )
    greenhouse_parser.add_argument("--candidate-slug", default="rebekah-love")

    greenhouse_sync_parser = subparsers.add_parser(
        "sync-greenhouse-job-boards",
        help="Run Greenhouse full-board Job Sync without candidate-facing discovery.",
    )
    greenhouse_sync_parser.add_argument("--board-token", action="append", default=[])
    greenhouse_sync_parser.add_argument("--candidate-slug", default=None)
    greenhouse_sync_parser.add_argument("--all-configured", action="store_true")
    greenhouse_sync_parser.add_argument("--force", action="store_true")
    greenhouse_sync_parser.add_argument("--freshness-hours", type=int, default=24)
    greenhouse_sync_parser.add_argument("--max-detail-requests", type=int, default=None)

    upsert_adzuna_signature_parser = subparsers.add_parser(
        "upsert-adzuna-sync-signature",
        help="Create or update an Adzuna broad Job Sync signature from explicit criteria.",
    )
    upsert_adzuna_signature_parser.add_argument("--query", required=True)
    upsert_adzuna_signature_parser.add_argument("--location", default=None)
    upsert_adzuna_signature_parser.add_argument("--provider-country", default=None)
    upsert_adzuna_signature_parser.add_argument("--provider-where", default=None)
    upsert_adzuna_signature_parser.add_argument("--query-kind", default="manual")
    upsert_adzuna_signature_parser.add_argument("--source", default="cli")
    upsert_adzuna_signature_parser.add_argument("--results-per-page", type=int, default=50)
    upsert_adzuna_signature_parser.add_argument("--max-pages", type=int, default=1)
    upsert_adzuna_signature_parser.add_argument("--freshness-hours", type=int, default=24)
    upsert_adzuna_signature_parser.add_argument("--enabled", dest="enabled", action="store_true", default=True)
    upsert_adzuna_signature_parser.add_argument("--disabled", dest="enabled", action="store_false")
    upsert_adzuna_signature_parser.add_argument("--created-by", default=None)

    list_adzuna_signatures_parser = subparsers.add_parser(
        "list-adzuna-sync-signatures",
        help="List persisted Adzuna broad Job Sync signatures.",
    )
    list_adzuna_signatures_parser.add_argument("--status", default=None)
    list_adzuna_signatures_parser.add_argument("--enabled-only", action="store_true")

    sync_adzuna_signatures_parser = subparsers.add_parser(
        "sync-adzuna-job-signatures",
        help="Refresh persisted Adzuna broad Job Sync signatures.",
    )
    sync_adzuna_signatures_parser.add_argument("--signature-id", action="append", default=[])
    sync_adzuna_signatures_parser.add_argument("--all-enabled", action="store_true")
    sync_adzuna_signatures_parser.add_argument("--force", action="store_true")
    sync_adzuna_signatures_parser.add_argument("--freshness-hours", type=int, default=None)
    sync_adzuna_signatures_parser.add_argument("--max-pages", type=int, default=None)

    list_location_mappings_parser = subparsers.add_parser(
        "list-job-location-mappings",
        help="List Job Sync provider location mappings needing review or maintenance.",
    )
    list_location_mappings_parser.add_argument("--status", default="needs_review")
    list_location_mappings_parser.add_argument("--provider-name", default=None)

    update_location_mapping_parser = subparsers.add_parser(
        "update-job-location-mapping",
        help="Update a Job Sync provider location mapping after review.",
    )
    update_location_mapping_parser.add_argument("--mapping-id", required=True)
    update_location_mapping_parser.add_argument("--provider-country", default=None)
    update_location_mapping_parser.add_argument("--provider-where", default=None)
    update_location_mapping_parser.add_argument("--confidence", default=None)
    update_location_mapping_parser.add_argument("--verification-status", default="verified")

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
    elif args.command == "seed-greenhouse-companies":
        seed_greenhouse_companies_command(candidate_slug=args.candidate_slug)
    elif args.command == "sync-greenhouse-job-boards":
        sync_greenhouse_job_boards_command(
            board_tokens=args.board_token,
            candidate_slug=args.candidate_slug,
            all_configured=args.all_configured,
            force=args.force,
            freshness_hours=args.freshness_hours,
            max_detail_requests=args.max_detail_requests,
        )
    elif args.command == "upsert-adzuna-sync-signature":
        upsert_adzuna_sync_signature_command(
            query=args.query,
            location=args.location,
            provider_country=args.provider_country,
            provider_where=args.provider_where,
            query_kind=args.query_kind,
            source=args.source,
            results_per_page=args.results_per_page,
            max_pages=args.max_pages,
            freshness_hours=args.freshness_hours,
            enabled=args.enabled,
            created_by=args.created_by,
        )
    elif args.command == "list-adzuna-sync-signatures":
        list_adzuna_sync_signatures_command(status=args.status, enabled_only=args.enabled_only)
    elif args.command == "sync-adzuna-job-signatures":
        sync_adzuna_job_signatures_command(
            signature_ids=args.signature_id,
            all_enabled=args.all_enabled,
            force=args.force,
            freshness_hours=args.freshness_hours,
            max_pages=args.max_pages,
        )
    elif args.command == "list-job-location-mappings":
        list_job_location_mappings_command(status=args.status, provider_name=args.provider_name)
    elif args.command == "update-job-location-mapping":
        update_job_location_mapping_command(
            mapping_id=args.mapping_id,
            provider_country=args.provider_country,
            provider_where=args.provider_where,
            confidence=args.confidence,
            verification_status=args.verification_status,
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


def seed_greenhouse_companies_command(*, candidate_slug: str) -> None:
    engine = create_db_engine()
    with Session(engine) as session:
        candidate_profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == candidate_slug))
        if candidate_profile is None:
            raise SystemExit(f"Candidate profile not found: {candidate_slug}")
        links = upsert_greenhouse_companies_for_candidate(session, candidate_profile_id=candidate_profile.id)
        session.commit()
        print(f"Upserted {len(links)} Greenhouse company link(s) for candidate profile: {candidate_slug}")


def sync_greenhouse_job_boards_command(
    *,
    board_tokens: list[str],
    candidate_slug: str | None,
    all_configured: bool,
    force: bool,
    freshness_hours: int,
    max_detail_requests: int | None,
) -> None:
    if not board_tokens and not candidate_slug and not all_configured:
        raise SystemExit("Pass --board-token, --candidate-slug, or --all-configured.")
    engine = create_db_engine()
    settings = load_settings()
    with Session(engine) as session:
        candidate_profile_id = None
        if candidate_slug:
            candidate_profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == candidate_slug))
            if candidate_profile is None:
                raise SystemExit(f"Candidate profile not found: {candidate_slug}")
            candidate_profile_id = candidate_profile.id
        results = sync_greenhouse_boards(
            session,
            settings=settings,
            candidate_profile_id=candidate_profile_id,
            board_tokens=board_tokens,
            include_configured=all_configured,
            force=force,
            freshness_hours=freshness_hours,
            max_detail_requests=max_detail_requests,
        )
        session.commit()
    if not results:
        print("No Greenhouse board sync targets matched.")
        return
    for result in results:
        print(format_greenhouse_sync_result(result))


def format_greenhouse_sync_result(result) -> str:
    diagnostics = result.diagnostics_json
    request = result.request
    if result.status == "skipped_fresh":
        return (
            f"{request.sync_key} skipped_fresh "
            f"latest_completed_at={diagnostics.get('latestCompletedAt') or '-'}"
        )
    if result.status == "failed":
        return f"{request.sync_key} failed error={result.error or '-'}"
    return (
        f"{request.sync_key} {result.status} raw={result.raw_result_count} "
        f"normalized={result.normalized_count} created={result.created_count} "
        f"updated={result.updated_count} closed={result.closed_count} "
        f"failed={result.failed_normalization_count} "
        f"detail={diagnostics.get('detailRequestsSucceeded', 0)}/{diagnostics.get('detailRequestsAttempted', 0)} "
        f"failed_detail={diagnostics.get('detailRequestsFailed', 0)} "
        f"skipped_detail={diagnostics.get('detailRequestsSkippedByGuardrail', 0)}"
    )


def upsert_adzuna_sync_signature_command(
    *,
    query: str,
    location: str | None,
    provider_country: str | None,
    provider_where: str | None,
    query_kind: str,
    source: str,
    results_per_page: int,
    max_pages: int,
    freshness_hours: int,
    enabled: bool,
    created_by: str | None,
) -> None:
    if not location and not provider_country:
        raise SystemExit("Pass --location or --provider-country.")
    engine = create_db_engine()
    with Session(engine) as session:
        signature = upsert_adzuna_sync_signature(
            session,
            query_text=query,
            display_location=location,
            provider_country=provider_country,
            provider_where=provider_where,
            query_kind=query_kind,
            source=source,
            results_per_page=results_per_page,
            max_pages=max_pages,
            freshness_hours=freshness_hours,
            enabled=enabled,
            created_by=created_by,
        )
        session.commit()
        print(format_adzuna_signature_upsert(signature))


def list_adzuna_sync_signatures_command(*, status: str | None, enabled_only: bool) -> None:
    engine = create_db_engine()
    with Session(engine) as session:
        statement = select(JobSyncSignature).where(JobSyncSignature.provider_name == "adzuna")
        if status:
            statement = statement.where(JobSyncSignature.verification_status == status)
        if enabled_only:
            statement = statement.where(JobSyncSignature.enabled.is_(True))
        signatures = list(session.scalars(statement.order_by(JobSyncSignature.created_at.asc(), JobSyncSignature.sync_key.asc())).all())
    if not signatures:
        print("No Adzuna sync signatures matched.")
        return
    for signature in signatures:
        print(format_adzuna_signature(signature))


def sync_adzuna_job_signatures_command(
    *,
    signature_ids: list[str],
    all_enabled: bool,
    force: bool,
    freshness_hours: int | None,
    max_pages: int | None,
) -> None:
    if not signature_ids and not all_enabled:
        raise SystemExit("Pass --signature-id or --all-enabled.")
    engine = create_db_engine()
    settings = load_settings()
    with Session(engine) as session:
        results = sync_adzuna_signatures(
            session,
            settings=settings,
            signature_ids=signature_ids or None,
            enabled_only=all_enabled,
            force=force,
            freshness_hours=freshness_hours,
            max_pages=max_pages,
        )
        session.commit()
    if not results:
        print("No Adzuna sync signatures matched.")
        return
    for result in results:
        print(format_adzuna_sync_result(result))


def format_adzuna_signature(signature: JobSyncSignature) -> str:
    criteria = signature.criteria_json or {}
    return (
        f"{signature.id} | {signature.sync_key} | query={signature.query_text} "
        f"location={signature.display_location or '-'} provider_country={signature.provider_country or '-'} "
        f"provider_where={signature.provider_where or '-'} enabled={signature.enabled} "
        f"status={signature.verification_status} api_path={criteria.get('apiPath') or '-'} "
        f"what={criteria.get('what') or signature.query_text or '-'} where={criteria.get('where') or '-'} "
        f"max_pages={signature.max_pages} results_per_page={signature.results_per_page} "
        f"last_completed_at={signature.last_completed_at or '-'} "
        f"last_status={signature.last_status or '-'} raw={signature.last_raw_result_count} "
        f"normalized={signature.last_normalized_count} created={signature.last_created_count} "
        f"updated={signature.last_updated_count}"
    )


def format_adzuna_signature_upsert(signature: JobSyncSignature) -> str:
    criteria = signature.criteria_json or {}
    return "\n".join(
        [
            "Adzuna sync signature upserted.",
            f"id: {signature.id}",
            f"sync_key: {signature.sync_key}",
            f"query: {signature.query_text}",
            f"location: {signature.display_location or '-'}",
            f"provider_country: {signature.provider_country or '-'}",
            f"provider_where: {signature.provider_where or '-'}",
            f"enabled: {signature.enabled}",
            f"verification_status: {signature.verification_status}",
            f"api_path: {criteria.get('apiPath') or '-'}",
            f"what: {criteria.get('what') or signature.query_text or '-'}",
            f"where: {criteria.get('where') or '-'}",
            f"max_pages: {signature.max_pages}",
            f"results_per_page: {signature.results_per_page}",
            "",
            "No provider API call was made. To fetch jobs, run:",
            (
                "python -m jobops_api.cli sync-adzuna-job-signatures "
                f"--signature-id {signature.id} --force --max-pages {signature.max_pages}"
            ),
        ]
    )


def format_adzuna_sync_result(result) -> str:
    diagnostics = result.diagnostics_json
    request = result.request
    criteria = request.criteria_json or {}
    api_path = criteria.get("apiPath") or "-"
    what = criteria.get("what") or request.query_text or "-"
    where = criteria.get("where") or request.provider_where or "-"
    if result.status == "skipped_fresh":
        return f"{request.sync_key} skipped_fresh latest_completed_at={diagnostics.get('latestCompletedAt') or '-'}"
    if result.status == "failed":
        return f"{request.sync_key} failed api={api_path} error={result.error or '-'}"
    if result.status == "skipped":
        return f"{request.sync_key} skipped api={api_path} reason={diagnostics.get('skipReason') or '-'}"
    return (
        f"{request.sync_key} {result.status} api={api_path} what={what} where={where} "
        f"pages={diagnostics.get('pagesFetched', criteria.get('maxPages') or 0)} "
        f"provider_count={diagnostics.get('providerReportedCount') or '-'} raw={result.raw_result_count} "
        f"normalized={result.normalized_count} created={result.created_count} updated={result.updated_count} "
        f"failed={result.failed_normalization_count}"
    )


def list_job_location_mappings_command(*, status: str, provider_name: str | None) -> None:
    engine = create_db_engine()
    with Session(engine) as session:
        ensure_initial_job_location_mappings(session)
        statement = (
            select(JobProviderLocationMapping, JobLocationTarget)
            .join(JobLocationTarget, JobLocationTarget.id == JobProviderLocationMapping.job_location_target_id)
            .order_by(JobLocationTarget.display_name.asc(), JobProviderLocationMapping.provider_name.asc())
        )
        if status:
            statement = statement.where(JobProviderLocationMapping.verification_status == status)
        if provider_name:
            statement = statement.where(JobProviderLocationMapping.provider_name == provider_name)
        rows = list(session.execute(statement))
        session.commit()
    if not rows:
        print("No Job Sync location mappings matched.")
        return
    for mapping, target in rows:
        print(
            f"{mapping.id} | target={target.display_name} ({target.normalized_key}) | "
            f"provider={mapping.provider_name} country={mapping.provider_country or '-'} "
            f"where={mapping.provider_where or '-'} confidence={mapping.confidence} "
            f"status={mapping.verification_status}"
        )


def update_job_location_mapping_command(
    *,
    mapping_id: str,
    provider_country: str | None,
    provider_where: str | None,
    confidence: str | None,
    verification_status: str,
) -> None:
    engine = create_db_engine()
    with Session(engine) as session:
        mapping = session.get(JobProviderLocationMapping, mapping_id)
        if mapping is None:
            raise SystemExit(f"Job provider location mapping not found: {mapping_id}")
        if provider_country is not None:
            mapping.provider_country = provider_country.strip().casefold() or None
        if provider_where is not None:
            mapping.provider_where = provider_where.strip() or None
        if confidence is not None:
            mapping.confidence = confidence.strip() or mapping.confidence
        mapping.verification_status = verification_status.strip() or mapping.verification_status
        session.commit()
        print(
            f"Updated mapping {mapping.id}: provider={mapping.provider_name} "
            f"country={mapping.provider_country or '-'} where={mapping.provider_where or '-'} "
            f"confidence={mapping.confidence} status={mapping.verification_status}"
        )


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
            session.execute(delete(CandidateCompany).where(CandidateCompany.candidate_profile_id == profile_id))
        session.execute(delete(CommandInteractionLog).where(CommandInteractionLog.tenant_id == tenant.id))
        session.execute(delete(UserSession).where(UserSession.tenant_id == tenant.id))
        session.commit()
        print(f"Reset mutable test data for workspace: {workspace_slug}")


if __name__ == "__main__":
    main()
