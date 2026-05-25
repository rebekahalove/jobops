# jobops
JobOps is an AI job-search operations platform for serious technical candidates, featuring a candidate-agent portfolio, role-fit analysis, and agent-readable hiring endpoints.

This root README is the canonical quickstart and high-level route overview. Detailed architecture, local development, model, deployment, and product design docs live in [`docs/`](docs/).

## Local Quickstart

JobOps is local-first during alpha. It has username/password auth, invite-based onboarding, tenant-scoped persistence, and no billing, scraping, or paid-service requirements. Model-assisted workflows can run in deterministic mock mode, with live Gemini available only when configured server-side.

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

The portfolio app routes are:

```text
/                         # public portfolio for the request hostname
/portfolio                # explicit default public portfolio route
/portfolio/<tenant-slug>  # alpha tenant/profile portfolio route
/jobops/about             # mounted public alpha landing page
/jobops                   # mounted private JobOps dashboard/command center
```

The public candidate-agent chat is embedded in the portfolio page. There is intentionally no `/portfolio/.../agent` page in this alpha slice.

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

The Profile workspace at `/profile` includes command-center intake for resume text, LinkedIn profile text, portfolio bios, and other background material. Model-assisted draft extraction runs through FastAPI, includes the current draft profile in the model request, persists private generated rows, and keeps generated content private/unpublished until the user reviews it. Users can edit generated items, publish field/item-level content as Private or Public, archive suppressed values, and manage public items through the portfolio preview. File upload and URL extraction are not part of this alpha slice yet.

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

Profile publishing works item by item: generated items remain private and unpublished until the user publishes them as Private or Public, and public portfolio output only includes published Public content.

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
