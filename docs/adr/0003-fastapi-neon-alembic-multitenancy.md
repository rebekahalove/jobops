# ADR 0003: FastAPI, Neon Postgres, Alembic, and Multi-Tenant Domain Mapping

Status: Accepted

## Context

JobOps is not only a public portfolio. It is intended to become a production-ready, multi-tenant job-search operations platform.

The first tenant is Rebekah Love. Future tenants may be invited candidates who set up profiles through resumes, interviews, GitHub or other sources, and then publish a candidate-agent profile page on a JobOps-hosted or custom domain.

The system needs a real database as soon as it starts managing private application history, profile facts, saved role-fit analyses, usage events, and tenant-specific data.

## Decision

Use:

- FastAPI for the backend API.
- Neon Postgres as the initial managed Postgres provider.
- SQLAlchemy for database models and data access.
- Alembic for database migrations.
- OpenAPI as the API contract between backend and frontends.
- Generated TypeScript clients for Next.js apps.

Model domain names as data rather than identity.

Initial domain mapping:

```text
rebekahalove.dev -> candidate_profile: rebekah-love
jobops.rebekahalove.dev -> dashboard for tenant: rebekah-love
```

Future domain mappings:

```text
rebekah.jobops.com -> candidate_profile: rebekah-love
joeblow.jobops.com -> candidate_profile: joe-blow
joeblow.me -> candidate_profile: joe-blow
```

## Consequences

Positive:

- The first deployment can grow into a multi-tenant system without replacing the data layer.
- Alembic gives explicit, reviewable database migrations.
- FastAPI and OpenAPI create a clean boundary between frontend apps and backend behavior.
- Neon provides a practical managed Postgres starting point.
- Custom domains and future product domains are routing records, not hard-coded assumptions.

Tradeoffs:

- The project becomes polyglot from the beginning.
- Local development and CI need both Node and Python setup.
- The backend requires a deployment target in addition to the frontend host.
- Database migrations add process overhead, but that overhead is useful once CRUD exists.

## Data Policy

Committed files may include approved public seed data, sanitized fixtures, eval cases, and docs.

Postgres should store managed platform data, including:

- Tenants.
- Users, once auth is implemented.
- Candidate profiles.
- Verified profile facts.
- Domain mappings.
- Target companies.
- Applications.
- Application events.
- Saved role-fit analyses.
- Follow-up records.
- Usage and quality events.

Raw chat messages and pasted job descriptions should not be stored by default. If stored later, they need consent, retention, redaction, and tenant-isolation policies.
