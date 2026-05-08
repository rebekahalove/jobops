# CI/CD Plan

## Pull Request Checks

GitHub Actions should run on every pull request:

- Install dependencies.
- Validate formatting.
- Lint.
- Typecheck.
- Run Python linting and formatting checks.
- Run Python type checks where practical.
- Run unit tests.
- Run integration tests.
- Run Alembic migration checks against a fresh Postgres service.
- Run schema validation against public profile data.
- Generate or validate OpenAPI and TypeScript API clients.
- Run deterministic eval smoke tests.
- Run deterministic adversarial smoke tests.
- Build affected apps.

PR checks should not require live model credentials. Use mock model adapters and deterministic fixtures by default.

PR checks should not require Neon credentials. Database tests should use a disposable Postgres service in CI.

## Main Branch Checks

On merge to `main`:

- Run the full deterministic test suite.
- Run backend tests and migration checks.
- Build the portfolio app.
- Build the private dashboard app when it exists.
- Deploy the Next.js frontend to Netlify if configured.
- Deploy the FastAPI backend to Render if configured.
- Publish a build or deployment summary.

## Optional Scheduled Checks

Nightly or on-demand checks can include:

- Live-model eval suite with budget limits.
- Dependency vulnerability scans.
- Link checks.
- Lighthouse or accessibility audits.

These should be configured so a missing model key does not break normal local development or PR validation.

## Required Secrets

Initial production deployment may eventually need:

- Model provider API key.
- Neon database connection string.
- Netlify token or Git integration for frontend deploys.
- Render API key or Git integration for backend deploys.
- Analytics token, if analytics are approved.

Secrets must only live in GitHub Actions secrets, Netlify environment variables, Render environment variables, Neon, or another approved secret manager. They must not be committed.

## Branch Protection Recommendation

Before public launch:

- Require PR review for `main`.
- Require CI checks to pass.
- Require branches to be up to date before merge.
- Block force pushes to `main`.
