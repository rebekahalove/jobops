from __future__ import annotations

import argparse

from sqlalchemy.orm import Session

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

    args = parser.parse_args()

    if args.command == "seed-public-profile":
        seed_public_profile_command(hostname=args.hostname)


def seed_public_profile_command(hostname: str | None = None) -> None:
    profile = load_public_seed_profile()
    engine = create_db_engine()
    with Session(engine) as session:
        candidate_profile = seed_public_profile(session, profile, hostname=hostname)
        candidate_slug = candidate_profile.slug
        session.commit()

    print(f"Seeded candidate profile: {candidate_slug}")


if __name__ == "__main__":
    main()
