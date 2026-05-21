# JobOps Dashboard

Private JobOps dashboard shell for an AI-first job-search command center.

```powershell
corepack pnpm dev:jobops
```

Then open:

```text
http://localhost:3002
```

On Windows, run long-lived dev servers in a dedicated terminal. If starting this command from `cmd.exe` or a script, use `call corepack pnpm dev:jobops` so the parent shell stays alive. See [Local Development](../../docs/local-development.md) for the full local server checklist.

## Alpha Session Auth

The dashboard uses persisted alpha user sessions. Seed an initial user with `jobops_api.cli seed-initial-user`, then sign in with that username. This is alpha auth, not full SaaS authentication; OAuth, password reset, billing, complex RBAC, and polished onboarding remain future work.

For local development only, `JOBOPS_DASHBOARD_AUTH_DISABLED=true` can bypass the session gate.

The local `dev` and `start` scripts load the repo-root `.env` and `.env.<APP_ENV>` files before starting Next so middleware and server routes use the same private values.

## Footer Build Metadata

Every JobOps page shows a subtle footer line such as:

```text
JobOps alpha · dev · build local
```

The footer is display-only alpha support metadata so testers can report which build they used. It is not stored in the database and does not require manual version increments. Missing values fall back to `alpha`, the current `APP_ENV` or `dev`, and `local`.

Safe frontend variables can be set directly:

```text
NEXT_PUBLIC_JOBOPS_RELEASE_CHANNEL=alpha
NEXT_PUBLIC_JOBOPS_APP_ENV=prod
NEXT_PUBLIC_JOBOPS_COMMIT_SHA=<commit sha>
NEXT_PUBLIC_JOBOPS_BUILD_TIME=<iso timestamp>
```

The helper also recognizes common deployment metadata such as Netlify `COMMIT_REF` / `CONTEXT`, Vercel `VERCEL_GIT_COMMIT_SHA` / `VERCEL_ENV`, Render `RENDER_GIT_COMMIT`, GitHub Actions `GITHUB_SHA`, and Cloudflare Pages `CF_PAGES_COMMIT_SHA`. Only the app name, release channel, environment, short commit, and optional build time are exposed to the browser. Do not expose secrets with `NEXT_PUBLIC_*`.

## AI Command Center Shell

The private app now centers on one JobOps command panel at the top of the shell, with workspace tabs below it:

- Profile
- Companies
- Jobs
- Applications
- Materials
- Follow-ups

The command center posts through the thin Next.js `/api/command-center` proxy to FastAPI. FastAPI owns agent command routing, tool execution, model calls, job URL intake, company follow, fit analysis, materials generation, and persistence. Next.js remains UI and thin proxy only.

The first real command-center tool is `profile_intake`. Other action cards remain planned/fallback behavior until their tools are implemented.

See [AI Command Center Shell](../../docs/ai-command-center-shell.md).

## Profile Workspace Shell

The `/profile` page is now a structured review surface for saved profile draft state:

- Guidance to use the JobOps command center above.
- Latest saved profile-intake status.
- Target role intent.
- Draft facts and claims.
- Skills.
- Experience and projects.
- Evidence links.
- Clarifying questions.
- Thin Next.js API proxy to the FastAPI profile draft endpoint.
- Mock provider support in FastAPI for deterministic local/test behavior.
- Live Gemini support in FastAPI when `JOBOPS_LLM_PROVIDER=gemini` and `GEMINI_API_KEY` are configured server-side.
- Pydantic structured output validation before draft state is updated.
- DB-backed persistence for validated draft profile data and redacted intake events.

Generated data is always treated as:

- `draft`
- `needs_review`
- source-labeled as `chat`, `resume`, or `model`
- `private`
- `published: false`

Review queues are grouped by information type rather than status. The saved draft snapshot remains local-dev/profile-scoped until auth exists. Approval, public-ready, and publish controls are intentionally deferred.

See [Command-Center Profile Workspace](../../docs/profile-workspace-design.md).

## Profile Intake Model Modes

The JobOps app expects the FastAPI service to be running at `JOBOPS_API_BASE_URL`, usually `http://localhost:8000`.
Next.js owns the UI and proxy only; prompt construction, model calls, validation, persistence, debug logging, and local artifact saving live in `services/api`. Shared provider/model routing lives in the Python `jobops_api.model_connector` module.

Mock mode, recommended for local UI work and tests:

```text
APP_ENV=dev
JOBOPS_LLM_PROVIDER=mock
JOBOPS_DEFAULT_MODEL=gemini-2.5-flash
JOBOPS_CHEAP_MODEL=gemini-2.5-flash-lite
```

Live Gemini mode:

```text
APP_ENV=dev
JOBOPS_LLM_PROVIDER=gemini
GEMINI_API_KEY=your_local_key
JOBOPS_DEFAULT_MODEL=gemini-2.5-flash
JOBOPS_CHEAP_MODEL=gemini-2.5-flash-lite
```

Keep provider keys in ignored local files such as `.env.dev`; never prefix them with `NEXT_PUBLIC_`.

## Local Intake Debug Artifacts

To inspect malformed live model output locally:

```text
JOBOPS_PROFILE_INTAKE_SAVE_ARTIFACTS=true
JOBOPS_PROFILE_INTAKE_SAVE_RAW_TEXT=false
```

Artifacts are written to `artifacts/profile-intake/<timestamp>_<runId>/` and are gitignored. Raw prompt/response capture is off by default. Set `JOBOPS_PROFILE_INTAKE_SAVE_RAW_TEXT=true` only when debugging locally, because raw artifacts may contain resume or chat content.

## Intentionally Deferred

- Authentication.
- Permanent raw resume storage.
- Full profile generator agent loop beyond the first command-center tool.
- Human approval workflow.
- Public fact publication.
- Job URL fetching/extraction.
- Company discovery/search.
- Job prioritization.
- Fit analysis.
- Materials generation.
- Browser automation.

Recommended next step: add explicit review actions for approving/rejecting persisted draft profile sections and items.
