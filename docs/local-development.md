# Local Development

This first scaffold is intentionally small. It does not include:

- Paid services.
- Auth.
- Scraping.
- Email integration.

## Prerequisites

- Node.js 22 or newer.
- `pnpm` through Corepack.
- Python 3.14 if you want to run the FastAPI scaffold.

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

The candidate-agent UI is available at:

```text
http://localhost:3000/agent
```

The app uses local mock behavior until verified public profile facts and the real backend workflow are implemented.

## Run The JobOps Dashboard Stub

The dashboard shell is the private JobOps app scaffold. It does not include auth, database-backed workflows, job intake, fit scoring, material generation, or persistence yet.

```powershell
corepack pnpm dev:jobops
```

Then open:

```text
http://localhost:3002
```

The stub includes placeholder workflow areas for:

- Profile.
- Jobs.
- Fit Scoring.
- Materials.
- Applications.

The Profile area is emphasized as the recommended first step because the next planned feature is the profile generator: resume upload or paste, LLM extraction into draft structured data, and clarifying questions to fill gaps.

The `/profile` route now includes a conversation-first profile intake shell. It opens with a large chat/intake panel, a prefilled `I want to be a...` message input, a prompt to paste resume text directly into the chat, a resume attachment affordance, a server-side intake extraction boundary, a change summary, a draft profile preview, and suggested clarifying questions. Structured target-role fields remain below the chat as a review/edit surface.

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

The server action boundary keeps the Gemini key server-side. The profile workspace does not persist raw resume text yet, and all generated claims are draft, source-labeled, private, unpublished, and marked needs review.

See [Conversation-First Profile Workspace](profile-workspace-design.md).

### Debug Profile Intake Model Runs

Malformed JSON from a live provider should fail safely. To inspect those failures locally, enable profile-intake artifacts in `.env.dev`:

```text
JOBOPS_PROFILE_INTAKE_SAVE_ARTIFACTS=true
JOBOPS_PROFILE_INTAKE_SAVE_RAW_TEXT=false
```

With raw text disabled, JobOps writes local metadata and validation issues only. Artifacts are written under:

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

This may write `prompt.txt`, `raw-response.txt`, and `parsed-output.json`. These files may contain resume text, chat content, and model-derived profile data. Keep this mode local only. The `artifacts/` directory is gitignored and must not be committed.

Suggested malformed JSON debugging flow:

1. Enable `JOBOPS_PROFILE_INTAKE_SAVE_ARTIFACTS=true`.
2. Reproduce the profile intake failure.
3. Note the `debugRunId` returned by the API or shown in the chat error.
4. Open the matching folder under `artifacts/profile-intake/`.
5. Review `metadata.json` and `validation-error.json`.
6. Enable `JOBOPS_PROFILE_INTAKE_SAVE_RAW_TEXT=true` only if metadata is not enough.

This is a local-only diagnostic layer, not the final system-wide observability design.

Deferred profile work:

- Database persistence.
- Human approval and publication workflow.
- Durable resume artifact handling.
- Full review controls.
- Telemetry.

Recommended next step: add persistence for validated draft profile intake output, keeping review and publication as explicit later actions.

## Run The API Scaffold

The API scaffold is optional for this first local run.

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

## Environment Files

The local env loader reads `.env`, then `.env.<APP_ENV>`.

For local dev:

```text
.env      -> APP_ENV=dev
.env.dev  -> local secrets such as DATABASE_URL
```

The backend database layer uses SQLAlchemy and Alembic. Keep the Neon connection string in `.env.dev`; it is ignored by Git and should never be committed.

The portfolio app also reads the repo-root `.env` and `.env.<APP_ENV>` on the server so it can find `JOBOPS_API_BASE_URL` during local development. Do not prefix private values with `NEXT_PUBLIC_`.

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

Start the API:

```powershell
cd C:\Users\rasho\jobops\services\api
.\.venv\Scripts\Activate.ps1
python -m uvicorn jobops_api.main:app --reload --port 8000
```

In another terminal, start the portfolio:

```powershell
cd C:\Users\rasho\jobops
corepack pnpm dev
```

With `JOBOPS_API_BASE_URL=http://localhost:8000` in `.env.dev`, the portfolio should show `Backend API` as its data source.
