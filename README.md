# jobops
JobOps is an AI job-search operations platform for serious technical candidates, featuring a candidate-agent portfolio, role-fit analysis, and agent-readable hiring endpoints.

## Local Quickstart

This first scaffold is local-first. It has no auth, scraping, email integration, billing, or paid-service requirements. Model-assisted profile intake can run in deterministic mock mode, with live Gemini available only when configured server-side.

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

The dashboard currently includes a profile-first app shell with placeholders for Profile, Jobs, Fit Scoring, Materials, and Applications. Auth, job intake, AI calls, fit scoring, and material generation are intentionally deferred. The recommended next feature is the profile generator.

The Profile workspace at `/profile` includes a local-only conversation-first intake shell with an `I want to be a...` prompt, resume paste directly in chat, resume attachment affordance, deterministic mock draft extraction, change summary, draft preview, clarifying questions, and structured review below the conversation.

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
