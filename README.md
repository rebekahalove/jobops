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

The JobOps experience now has a public alpha surface and a private authenticated app. Unauthenticated visitors to `/jobops` are sent to `/jobops/about`, which explains the build-in-public alpha, shows safe aggregate metrics, and accepts alpha access requests. Existing alpha users can log in from that page and continue to the private dashboard.

The dashboard currently includes profile intake, company tracking, application tracking, AI-assisted workflow commands, and placeholders for jobs, fit scoring, materials, and follow-ups. Billing, OAuth, email recovery, teams/RBAC, publishing, and job intake are intentionally deferred.

The Profile workspace at `/profile` includes a conversation-first intake flow with an `I want to be a...` prompt, resume paste directly in chat, model-assisted draft extraction through FastAPI, DB-backed draft persistence, redacted intake events, change summary, draft preview, clarifying questions, and structured review below the conversation.

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
