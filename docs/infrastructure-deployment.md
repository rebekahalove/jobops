# Infrastructure and Deployment Plan

## Initial Public MVP

Recommended first deployment target:

- Netlify site for `apps/portfolio`.
- Netlify site for `apps/jobops` when the dashboard shell exists.
- Render web service for `services/api`.
- Neon Postgres project for application data.
- Production domain: `rebekahalove.dev`.
- Dashboard domain: `jobops.rebekahalove.dev`.
- Preview deployments for pull requests.
- Server-side model calls only through the backend.
- `.env.example` committed, real secrets configured in Netlify, Render, GitHub Actions, or Neon.

This keeps the first public surface lightweight while avoiding a throwaway data architecture.

## Hosting Decision

Use the following initial split:

```text
Netlify       -> Next.js frontends
Render        -> FastAPI backend
Neon Postgres -> database
GitHub Actions -> CI checks
```

The hosting budget target is free or under $10/month before model API usage and domain registration. The expected baseline is:

```text
Netlify Free      $0/month
Render Starter    about $7/month
Neon Free         $0/month
```

Render is preferred over Fly.io for the first API host because it is a lower-operations platform for a small FastAPI service: Git deploys, environment variables, logs, managed TLS, custom domains, and `render.yaml` infrastructure-as-code are enough for this phase. Fly.io remains a good future option if JobOps needs more control over regions, Machines, autostop/autostart behavior, or container-first operations.

## Private JobOps Dashboard

`jobops.rebekahalove.dev` should start as a private dashboard shell and grow only through approved increments.

When private workflows begin, add:

- Authentication.
- Database-backed private data.
- Access controls.
- Audit logging.
- Clear data retention policy.
- Separate deployment and environment variables if needed.

Do not commit private operational records to this repo.

## Database Timing

Use Neon Postgres from the beginning for platform data that will be managed over time.

Store in Postgres:

- Tenant records.
- Candidate profiles.
- Published profile facts.
- Domain mappings.
- Private target-company tracking.
- Private application state.
- Follow-up history.
- Saved role-fit analyses.
- Multi-user access.
- Admin review workflows.
- Usage and quality events.

Short-lived untracked local JSON is acceptable for exploration, but once a data type gets CRUD, it belongs in Postgres and must be managed with Alembic migrations.

## Domain Strategy

Start with:

- `rebekahalove.dev` for Rebekah's public candidate-agent profile.
- `jobops.rebekahalove.dev` for Rebekah's private JobOps dashboard.

Design for later:

- JobOps-hosted candidate subdomains, if a product domain is purchased.
- Custom candidate domains mapped to candidate profiles.
- Canonical URL and redirect updates if the product moves from `rebekahalove.dev` to a future JobOps domain.

Changing domains later should be DNS, redirects, config, and database domain mapping work, not a rewrite. The database should model domains separately from candidate identity.

## Infrastructure as Code

Use lightweight configuration first:

- `netlify.toml` for frontend build, redirects, and deploy-context settings.
- `render.yaml` for API service infrastructure-as-code when useful.
- `.env.example`, `.env.dev.example`, and `.env.prod.example` for documented environment variables.
- GitHub Actions workflow files for CI/CD.
- Alembic migrations for database schema.

Consider Terraform or OpenTofu later for:

- DNS records.
- Netlify project settings.
- Render service settings.
- API deployment settings.
- Database provisioning.
- Secret manager configuration.

Avoid adding IaC before the resource surface is real enough to justify it.

## Observability

Initial observability:

- Structured server logs without raw job descriptions or secrets.
- Latency and error metrics.
- Tenant-scoped usage metrics.
- Output validation failure counts.
- Eval and adversarial test reports.
- Database migration and query health signals.

Before adding product analytics, choose an analytics tool and define a privacy policy for event payloads.
