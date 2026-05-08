# Files to Create First

This is the recommended creation order after the planning checkpoint is approved.

## Planning and Governance

Already created in this planning pass:

- `README.md`
- `docs/architecture.md`
- `docs/repo-structure.md`
- `docs/milestone-01.md`
- `docs/metrics.md`
- `docs/testing-evals.md`
- `docs/security-adversarial-testing.md`
- `docs/ci-cd.md`
- `docs/infrastructure-deployment.md`
- `docs/data-model.md`
- `docs/candidate-profile-intake.md`
- `docs/environment.md`
- `docs/adr/0001-monorepo-platform-structure.md`
- `docs/adr/0002-grounded-agent-contract.md`
- `docs/adr/0003-fastapi-neon-alembic-multitenancy.md`
- `docs/adr/0004-netlify-render-neon-hosting.md`

## First Scaffold Files

Create next, only after approval:

- `.gitignore`
- `.env.example`
- `.env.dev.example`
- `.env.prod.example`
- `package.json`
- `pnpm-workspace.yaml`
- `tsconfig.base.json`
- `services/api/README.md`
- `services/api/pyproject.toml`
- `services/api/jobops_api/main.py`
- `services/api/jobops_api/settings.py`
- `services/api/tests/test_health.py`
- `services/api/tests/test_settings.py`
- `.github/workflows/ci.yml`
- `apps/portfolio/README.md`
- `apps/jobops/README.md`
- `packages/contracts/package.json`
- `packages/contracts/src/index.ts`
- `packages/contracts/src/generated/`
- `packages/profile/package.json`
- `packages/profile/src/index.ts`
- `packages/profile/data/rebekah-love.public.seed.json`

## First Test Files

Create with the initial scaffold:

- `packages/contracts/tests/role-fit-contract.test.ts`
- `packages/profile/tests/public-seed.test.ts`
- `services/api/tests/test_candidate_profile.py`
- `services/api/tests/test_domain_resolution.py`
- `packages/evals/cases/candidate-qa.initial.json`
- `packages/evals/cases/role-fit.initial.json`
- `packages/security-harness/cases/prompt-injection.initial.json`

## Approval Needed

Before creating scaffold files, confirm:

- Package manager: recommended `pnpm`.
- Web framework: recommended Next.js.
- Backend framework: recommended FastAPI.
- Database: recommended Neon Postgres.
- Migrations: recommended Alembic.
- Test runner: recommended Vitest.
- Backend test runner: recommended Pytest.
- Browser runner: recommended Playwright once UI exists.
- Frontend deployment target: recommended Netlify.
- API deployment target: recommended Render.
- API contracts: recommended OpenAPI plus generated TypeScript clients.

Database files such as Alembic migrations, SQLAlchemy models, and DB sessions are part of the first explicit database increment.
