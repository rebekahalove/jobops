# jobops
JobOps is an AI job-search operations platform for serious technical candidates, featuring a candidate-agent portfolio, role-fit analysis, and agent-readable hiring endpoints.

## Local Quickstart

This scaffold is local-first. It has alpha username/password auth, invite-based onboarding, tenant-scoped persistence, and no billing, scraping, or paid-service requirements. Model-assisted profile intake can run in deterministic mock mode, with live Gemini available only when configured server-side.

```powershell
corepack enable
corepack prepare pnpm@9.15.4 --activate
corepack pnpm install
corepack pnpm dev:portfolio
```

Then open:

```text
http://localhost:3000
```

The candidate-agent scaffold is at:

```text
http://localhost:3000/agent
```

The JobOps dashboard runs separately:

```powershell
corepack pnpm dev:jobops
```

Then open:

```text
http://localhost:3002
```

The JobOps experience now has a public alpha surface and a private authenticated app. Unauthenticated visitors to `/jobops` are sent to `/jobops/about`, which explains the build-in-public alpha, shows safe aggregate metrics, and accepts alpha access requests. Existing alpha users with a valid `jobops_session` cookie see command-center CTAs on `/about` and `/jobops/about` instead of being asked to log in again.

The dashboard currently includes profile intake, profile review/publishing, company tracking, application tracking, AI-assisted workflow commands, and placeholders for jobs, fit scoring, materials, and follow-ups. Billing, OAuth, email recovery, teams/RBAC, and job intake are intentionally deferred.

The Profile workspace at `/profile` includes a paste-first intake flow for resume text, LinkedIn profile text, portfolio bios, and other background material. Model-assisted draft extraction runs through FastAPI, includes the current draft profile in the model request, persists private draft rows, and keeps generated facts private/unpublished until the user reviews them. Users can edit facts, mark visibility public/private, approve items, and publish approved public information. File upload and URL extraction are not part of this alpha slice yet.

## Alpha Operations

Create a local alpha invite from the API service:

```powershell
cd services/api
.\.venv\Scripts\python.exe -m jobops_api.cli create-alpha-invite --email user@example.com --base-url http://localhost:3002
```

To test session-aware alpha landing locally:

1. Run FastAPI on `http://127.0.0.1:8002` and the standalone JobOps app on `http://localhost:3002`.
2. Visit `http://localhost:3002/about` while logged out and confirm the page shows `Log in` and `Request alpha access`.
3. Log in through `http://localhost:3002/login`, then revisit `http://localhost:3002/about` and confirm it shows command-center CTAs.
4. For the production-mounted route, run the portfolio app and test `http://localhost:3000/jobops/about`.

Profile publishing works as an explicit review step: draft/model-generated items remain private and unpublished; public portfolio output only includes items with public visibility and published status. Approved public draft facts are promoted to published public profile facts when the user clicks publish.

During alpha, tenant portfolios live at:

```text
/portfolio/<tenant-slug>
```

For example, a workspace slug of `chance-alpha` maps to `/portfolio/chance-alpha`. Rebekah's root hostname portfolio remains hostname-routed through `rebekahalove.dev`. The older mounted `/jobops/portfolio/<tenant-slug>` route may still exist as a compatibility path, but the dashboard links to the root portfolio URL.

For local multi-service development, run the portfolio, dashboard, and API in separate terminals. See [Local Development](docs/local-development.md) for Windows-specific server startup and port cleanup notes.

## Planning Docs

- [Recommended Architecture](docs/architecture.md)
- [Initial Repo Structure](docs/repo-structure.md)
- [Initial Data Model](docs/data-model.md)
- [Candidate Profile Intake](docs/candidate-profile-intake.md)
- [Conversation-First Profile Workspace](docs/profile-workspace-design.md)
- [Model Connectors](docs/model-connectors.md)
- [Environment Configuration](docs/environment.md)
- [First Milestone](docs/milestone-01.md)
- [Metrics](docs/metrics.md)
- [Testing and Evals](docs/testing-evals.md)
- [Adversarial Testing](docs/security-adversarial-testing.md)
- [CI/CD Plan](docs/ci-cd.md)
- [Infrastructure and Deployment](docs/infrastructure-deployment.md)
- [First Files to Create](docs/first-files.md)
