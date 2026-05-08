# Milestone 1: Multi-Tenant Foundation and Grounded Public Portfolio Agent

## Outcome

A recruiter or hiring manager can visit the public portfolio app, learn who Rebekah Love is, ask grounded questions about her verified profile, and paste a job description to receive structured role-fit analysis.

Under the hood, this should be the first tenant of a multi-tenant JobOps platform, backed by a FastAPI service and Neon Postgres rather than a one-off static portfolio.

## Acceptance Criteria

- The portfolio app has a clear public landing page.
- The candidate-agent interface accepts natural-language questions.
- Answers are grounded only in verified structured profile data.
- Unknown or unsupported questions are refused or caveated.
- The role-fit workflow accepts a pasted job description.
- Role-fit output includes:
  - Fit score from 0 to 100.
  - Fit summary.
  - Matching strengths.
  - Gaps or concerns.
  - Suggested application positioning.
  - Recommended next step.
  - Suggested interview questions.
- Pasted job descriptions are treated as untrusted data.
- Prompt-injection attempts in job descriptions cannot override system behavior or candidate facts.
- The app does not expose secrets, environment variables, private notes, or private application data.
- The backend stores and serves published profile facts from Postgres.
- The domain model can map `rebekahalove.dev` to Rebekah's candidate profile without hard-coding that hostname as identity.
- CI runs lint, typecheck, Python checks, tests, build, eval smoke tests, adversarial smoke tests, and migration checks.

## Non-Goals

- No auth.
- No billing.
- No scraping.
- No email integration.
- No ATS integration.
- No autonomous application submission.
- No full private JobOps dashboard beyond a minimal shell unless separately approved.
- No multi-candidate onboarding UI yet.
- No custom-domain self-service UI yet.

## Scaffold 0: Local-Only First Increment

Completed as the first increment before database-backed milestone work:

- Next.js portfolio app.
- Local mock candidate-agent Q&A.
- Local mock role-fit workflow.
- Shared profile and contract packages.
- FastAPI scaffold with health and mock endpoints.
- Environment loader that understands `.env` and `.env.<APP_ENV>`.
- No database connection code in scaffold 0.
- No auth.
- No scraping.
- No email integration.
- No paid-service calls.

## First 10 Implementation Tasks

1. Initialize the monorepo with `pnpm`, TypeScript config, Python project conventions, `.gitignore`, `.env.example`, and baseline README updates.
2. Scaffold `services/api` with FastAPI, health check, settings loading, mock endpoints, and test setup.
3. Add SQLAlchemy, Alembic, and Neon connection code in the first explicit database increment.
4. Add `packages/profile` with Rebekah's approved public seed profile and a backend seed/import path.
5. Add `packages/contracts` with shared JSON Schema contracts and generated TypeScript API types from FastAPI OpenAPI.
6. Add backend candidate-profile, candidate Q&A, and role-fit endpoints using mock model support for tests.
7. Add `packages/prompts` with versioned prompt templates for candidate Q&A and role-fit analysis.
8. Scaffold `apps/portfolio` as a Next.js app that resolves `rebekahalove.dev` to Rebekah's published profile and calls the backend.
9. Add test coverage: backend unit/integration tests, migration tests, contract tests, frontend tests, and first Playwright smoke test.
10. Add `packages/evals`, `packages/security-harness`, and GitHub Actions workflows for deterministic eval and adversarial smoke checks.

## Exit Criteria

- Public MVP works locally.
- All required checks pass in CI.
- Database integration has a documented setup path and an initial Alembic migration.
- At least 10 Q&A eval cases pass.
- At least 5 role-fit eval cases pass.
- At least 10 prompt-injection or data-exposure adversarial cases pass.
- There is an explicit production deployment checklist.
