# Local Development

This alpha stack is intentionally local-first. It includes alpha username/password sessions, invite-based onboarding, tenant-scoped persistence, public portfolio routes, and backend-backed public candidate Q&A. It still does not include:

- Paid services.
- Scraping.
- Email integration.
- Billing, OAuth, teams/RBAC, or automated job intake.

## Prerequisites

- Node.js 22 or newer.
- `pnpm` through Corepack.
- Python 3.14 if you want to run the FastAPI service.

PowerShell may block `npm.ps1` or `pnpm.ps1` shims. If so, use `npm.cmd` or run package manager commands through Corepack.

## Install Frontend Dependencies

From the repo root:

```powershell
corepack enable
corepack prepare pnpm@9.15.4 --activate
corepack pnpm install
```

## Run Local Servers

For day-to-day development on Windows, prefer long-lived visible terminals. This keeps each dev server attached to a real console and makes `Ctrl+C` shutdown predictable.

Use one terminal per service:

```powershell
# Terminal 1: public portfolio at http://localhost:3000
cd C:\Users\rasho\jobops
corepack pnpm dev:portfolio
```

```powershell
# Terminal 2: JobOps dashboard at http://localhost:3002
cd C:\Users\rasho\jobops
corepack pnpm dev:jobops
```

```powershell
# Terminal 3: FastAPI service at http://localhost:8000
cd C:\Users\rasho\jobops\services\api
.\.venv\Scripts\Activate.ps1
python -m uvicorn jobops_api.main:app --reload --port 8000
```

If launching from a `cmd.exe` script or `cmd /k` command, use `call` before batch-style commands such as `corepack` or virtualenv shims:

```cmd
cd /d C:\Users\rasho\jobops
call corepack pnpm dev:jobops
```

Without `call`, Windows can exit the parent command shell after the batch command returns control, which may also tear down child dev-server processes.

When Codex starts servers for you, it may need to launch them outside the sandbox so they survive after the tool call finishes. If servers disappear immediately after starting, this is usually a process-lifetime issue rather than a Next.js or Uvicorn application error.

To check or clear stuck local ports:

```powershell
netstat -ano | Select-String ":3000|:3002|:8000"
Stop-Process -Id <PID> -Force
```

## Run The Portfolio App

```powershell
corepack pnpm dev
```

Then open:

```text
http://localhost:3000
```

The public portfolio and embedded candidate-agent chat are available at:

```text
http://localhost:3000/
http://localhost:3000/portfolio
```

When `JOBOPS_API_BASE_URL` is configured, the portfolio loads published public profile data from FastAPI and the embedded candidate-agent posts through the Next server route to the public FastAPI candidate-agent endpoint. Local development may still fall back to the committed seed profile when the API is unavailable; production shows a generic unavailable state instead of silently relying on seed data.

## Run The JobOps Dashboard

The dashboard is the private JobOps command center. It uses persisted alpha user sessions backed by FastAPI, invite-based onboarding, and tenant-scoped profile/application data. It does not include OAuth, billing, teams/RBAC, automated job intake, or password-reset email recovery. The command center can run profile intake through FastAPI, and the Profile workspace supports field/item-level Generated, Private, Public, and Archived review workflows.

```powershell
corepack pnpm dev:jobops
```

Then open:

```text
http://localhost:3002
```

For local development only, you may bypass the session gate with:

```text
JOBOPS_DASHBOARD_AUTH_DISABLED=true
```

Do not set that bypass in production.

The dashboard includes active Profile, Companies, and Applications areas plus placeholder or early workflow areas for:

- Jobs.
- Fit Scoring.
- Materials.
- Follow-ups.

The Profile area is emphasized as the recommended first step because profile intake turns pasted resume/profile/background text into generated field and item proposals for review.

The `/profile` route is a structured review/display surface. It no longer has its own chat composer. Use the AI Command Center above the workspace tabs to enter profile commands such as `I want to be an Applied AI Engineer.` The Profile route loads the latest generated proposals, published private fields/items, public portfolio preview, archived/suppressed values, evidence links, and clarifying questions.

The `/applications` route now includes the first manual Application Tracker MVP. It supports adding applications, listing saved applications, viewing status badges and next follow-up dates, keeping notes, and editing status. It intentionally does not scrape job posts, extract postings, score fit, generate cover letters, integrate Gmail/email, send reminders, or add OAuth/RBAC beyond the dashboard session gate.

The active command-center profile-intake backend lives in FastAPI at:

```text
POST http://localhost:8000/v1/command-center/commands
```

Use the configured FastAPI port from `JOBOPS_API_BASE_URL` if your local API is not running on `8000`.

The Profile workspace loads its field/item review state through:

```text
GET http://localhost:8000/v1/profile/current
GET http://localhost:8000/v1/command-center/profile-draft/current
```

The Next.js app keeps only thin proxies such as `/api/command-center`, `/api/profile`, and `/api/profile-draft`. It does not build prompts, call model providers, validate model output, or save artifacts. FastAPI calls the shared Python `jobops_api.model_connector` module for provider/model routing.

The dashboard session gate also protects the thin proxy routes used by the dashboard. FastAPI remains the authority for identity, tenant scoping, authorization, validation, and persistence. Alpha auth is intentionally smaller than full product auth: OAuth, complex RBAC, account recovery, and audit tooling are deferred.

For deterministic local mode:

```text
APP_ENV=dev
JOBOPS_LLM_PROVIDER=mock
JOBOPS_DEFAULT_MODEL=gemini-2.5-flash
JOBOPS_CHEAP_MODEL=gemini-2.5-flash-lite
```

For live Gemini mode:

```text
APP_ENV=dev
JOBOPS_LLM_PROVIDER=gemini
GEMINI_API_KEY=your_local_key
JOBOPS_DEFAULT_MODEL=gemini-2.5-flash
JOBOPS_CHEAP_MODEL=gemini-2.5-flash-lite
```

The FastAPI boundary keeps the Gemini key server-side. The profile workspace persists validated generated profile data to Postgres through FastAPI, but it still does not store raw resume/chat text in the database by default. Generated claims are review-only until the user publishes them as Private or Public; public portfolio output and public candidate-agent context include only published public content.

See [Command-Center Profile Workspace](profile-workspace-design.md).

### Debug Profile Intake Model Runs

Malformed JSON from a live provider should fail safely. To inspect those failures locally, enable profile-intake artifacts in `.env.dev`:

```text
JOBOPS_PROFILE_INTAKE_SAVE_ARTIFACTS=true
JOBOPS_PROFILE_INTAKE_SAVE_RAW_TEXT=false
```

With raw text disabled, JobOps writes local metadata, validation issues, and parsed structured output when parsing succeeds. Artifacts are written under:

```text
artifacts/profile-intake/<timestamp>_<runId>/
```

Typical files:

- `metadata.json`
- `request-metadata.json`
- `validation-error.json` when parsing or validation fails

For deeper local debugging, you can also enable raw prompt and response capture:

```text
JOBOPS_PROFILE_INTAKE_SAVE_ARTIFACTS=true
JOBOPS_PROFILE_INTAKE_SAVE_RAW_TEXT=true
```

This may write `prompt.txt` and `raw-response.txt`. `parsed-output.json` is written when artifacts are enabled and parsing succeeds. These files may contain resume text, chat content, and model-derived profile data. Keep artifact mode local only. The `artifacts/` directory is gitignored and must not be committed.

Suggested malformed JSON debugging flow:

1. Enable `JOBOPS_PROFILE_INTAKE_SAVE_ARTIFACTS=true`.
2. Reproduce the profile intake failure.
3. Note the `debugRunId` returned by the API or shown in the chat error.
4. Open the matching folder under `artifacts/profile-intake/`.
5. Review `metadata.json` and `validation-error.json`.
6. Enable `JOBOPS_PROFILE_INTAKE_SAVE_RAW_TEXT=true` only if metadata is not enough.

This is a local-only diagnostic layer, not the final system-wide observability design.

Command-center profile intake persistence flow:

```text
AI Command Center UI -> Next thin proxy -> FastAPI /v1/command-center/commands
  -> model connector -> Pydantic validation
  -> profile_intake_sessions + draft tables + redacted events
```

Tables reused:

- `profile_intake_sessions`
- `role_targets`
- `profile_fact_drafts`
- `skill_claims`
- `evidence_artifacts`

Tables added for this slice:

- `profile_field_values`
- `profile_intake_events`
- `experience_project_drafts`

Application tracker persistence flow:

```text
Applications UI -> Next thin proxy -> FastAPI /v1/applications
  -> companies + candidate_companies + job_roles + applications + application_events
```

Tables added for the manual Application Tracker MVP:

- `companies`
- `candidate_companies`
- `job_roles`
- `applications`
- `application_events`

Application tracker endpoints:

```text
POST /v1/applications
GET /v1/applications
PATCH /v1/applications/{application_id}/status
POST /v1/applications/{application_id}/events
```

See [Application Tracker MVP](application-tracker-mvp.md).

By default JobOps stores message lengths, draft counts, model run IDs, artifact paths, and safe event metadata. It does not store raw chat/resume text in the database. If raw artifact saving is explicitly enabled, raw prompt/response files stay local under gitignored `artifacts/`.

Profile-intake draft persistence now merges each model turn into the active saved draft. Empty arrays, empty strings, nulls, and omitted optional sections are treated as no-change patches, not delete instructions. Explicit clear/reset behavior is deferred until there is an intentional user action and a dedicated backend path for it.

Deferred profile work:

- Durable resume artifact handling.
- Richer profile revision history.
- Public rate limiting/abuse controls for model-backed public Q&A.
- Broader telemetry and observability.

Review/publishing is implemented at alpha depth; future work should deepen revision history and file extraction rather than reintroducing batch publishing.

## Run The API

The API service is required for authenticated dashboard workflows, profile publishing, public portfolio backend loading, and model-backed candidate Q&A.

From `services/api`:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m uvicorn jobops_api.main:app --reload --port 8000
```

Then open:

```text
http://localhost:8000/health
```

## Run The API With Docker

The API can also run as a local container without changing the accepted architecture. This builds only `services/api`; the Next.js frontends remain separate and are still hosted/developed outside the API image.

Make sure the usual local environment files exist first:

```text
.env      -> APP_ENV=dev
.env.dev  -> DATABASE_URL and local-only API/model settings
```

Build the image from the repo root:

```powershell
docker build -t jobops-api:local -f services/api/Dockerfile services/api
```

Run the API container directly:

```powershell
docker run --rm --env-file .env --env-file .env.dev -p 8000:8000 jobops-api:local
```

Or run through Docker Compose:

```powershell
docker compose up --build api
```

Smoke-test the API:

```powershell
Invoke-WebRequest -Uri http://localhost:8000/health -UseBasicParsing
```

Run migrations intentionally rather than as part of container startup:

```powershell
docker compose run --rm api python -m alembic upgrade head
```

This uses the same `DATABASE_URL` as local Python development, so Neon remains the default database path. A local Postgres container is not included because it would create a second default database workflow; add one later only if local-offline database work becomes a regular need.

## Environment Files

The local env loader reads `.env`, then `.env.<APP_ENV>`.

For local dev:

```text
.env      -> APP_ENV=dev
.env.dev  -> local secrets such as DATABASE_URL
```

The backend database layer uses SQLAlchemy and Alembic. Keep the Neon connection string in `.env.dev`; it is ignored by Git and should never be committed.

The portfolio and JobOps apps also read the repo-root `.env` and `.env.<APP_ENV>` on the server so they can find `JOBOPS_API_BASE_URL` during local development. Do not prefix private values with `NEXT_PUBLIC_`.

The local Next.js `dev` and `start` scripts load these files before starting Next so middleware can see the same private server-side values as route handlers.

Dashboard sessions are server-owned and stored in the backend `user_sessions` table. Do not store default user identity in `.env`.

## Database Setup

After `.env.dev` contains `DATABASE_URL`, apply migrations:

```powershell
cd C:\Users\rasho\jobops\services\api
.\.venv\Scripts\Activate.ps1
python -m alembic upgrade head
```

Seed the first public candidate profile shell:

```powershell
python -m jobops_api.cli seed-public-profile --hostname rebekahalove.dev
```

This creates the first tenant, candidate profile, and domain mapping. It does not publish unreviewed facts.

## Run The API And Portfolio Together

Start the API. Use the port configured by `JOBOPS_API_BASE_URL` in `.env.dev`; recent local JobOps work has commonly used `8002`, while older docs/examples used `8000`.

```powershell
cd C:\Users\rasho\jobops\services\api
.\.venv\Scripts\Activate.ps1
python -m uvicorn jobops_api.main:app --reload --host 127.0.0.1 --port 8002
```

In another terminal, start the portfolio:

```powershell
cd C:\Users\rasho\jobops
corepack pnpm dev
```

With `JOBOPS_API_BASE_URL=http://localhost:8002` in `.env.dev`, the portfolio loads public profile data from FastAPI. If you use a different backend port, update `.env.dev` before starting the frontend.

The current route structure is:

```text
http://localhost:3000/                         # portfolio app root, hostname-resolved portfolio
http://localhost:3000/portfolio                # explicit default portfolio route
http://localhost:3000/portfolio/<tenant-slug>  # alpha tenant portfolio
http://localhost:3000/jobops                   # mounted private JobOps dashboard
http://localhost:3000/jobops/about             # mounted public alpha page
http://localhost:3002/                         # standalone private JobOps dashboard
http://localhost:3002/portfolio                # standalone local portfolio route for dashboard QA
```

The public candidate-agent chat is embedded on the portfolio page. It posts to `/api/public/candidate-agent`, which calls FastAPI server-side at `/v1/public/portfolio/<profile-slug>/questions`. There is intentionally no `/portfolio/agent` or `/portfolio/<tenant-slug>/agent` page in this alpha slice.

Production portfolio fallback behavior is intentionally conservative: if the portfolio app cannot reach the backend in production, it shows a generic unavailable message and logs details server-side. Local development may still fall back to the committed seed profile.
