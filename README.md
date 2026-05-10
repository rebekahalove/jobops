# jobops
JobOps is an AI job-search operations platform for serious technical candidates, featuring a candidate-agent portfolio, role-fit analysis, and agent-readable hiring endpoints.

## Local Quickstart

This first scaffold is local-only. It has no auth, database connection, scraping, email integration, paid-service calls, or live model calls.

```powershell
corepack enable
corepack prepare pnpm@9.15.4 --activate
corepack pnpm install
corepack pnpm dev
```

Then open:

```text
http://localhost:3000
```

The candidate-agent scaffold is at:

```text
http://localhost:3000/agent
```

The JobOps dashboard stub runs separately:

```powershell
corepack pnpm dev:jobops
```

Then open:

```text
http://localhost:3002
```

The dashboard currently includes a profile-first app shell with placeholders for Profile, Jobs, Fit Scoring, Materials, and Applications. Auth, job intake, AI calls, fit scoring, and material generation are intentionally deferred. The recommended next feature is the profile generator.

The Profile workspace at `/profile` now includes a local-only intake shell with target-role intent fields, resume text paste, deterministic mock draft extraction, draft preview, and clarifying questions. It does not store resume text or call a live model.

## Planning Docs

- [Recommended Architecture](docs/architecture.md)
- [Initial Repo Structure](docs/repo-structure.md)
- [Initial Data Model](docs/data-model.md)
- [Candidate Profile Intake](docs/candidate-profile-intake.md)
- [Model Connectors](docs/model-connectors.md)
- [Environment Configuration](docs/environment.md)
- [First Milestone](docs/milestone-01.md)
- [Metrics](docs/metrics.md)
- [Testing and Evals](docs/testing-evals.md)
- [Adversarial Testing](docs/security-adversarial-testing.md)
- [CI/CD Plan](docs/ci-cd.md)
- [Infrastructure and Deployment](docs/infrastructure-deployment.md)
- [First Files to Create](docs/first-files.md)
