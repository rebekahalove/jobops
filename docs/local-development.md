# Local Development

This first scaffold is intentionally small and local-only.

It does not include:

- Paid services.
- Auth.
- Database connection code.
- Scraping.
- Email integration.
- Live model calls.

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

The dashboard shell is the private JobOps app scaffold. It does not include auth, database-backed workflows, job intake, fit scoring, material generation, or AI calls yet.

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

The `/profile` route now includes a conversation-first profile intake shell. It opens with a large chat/intake panel, a prefilled `I want to be a...` message input, a prompt to paste resume text directly into the chat, a resume attachment affordance, deterministic mock extraction, a change summary, a draft profile preview, and suggested clarifying questions. Structured target-role fields remain below the chat as a review/edit surface. The extractor is intentionally mocked: it does not call Gemini or any live provider, does not persist raw resume text, and marks generated claims as draft, source-labeled, not verified, and private.

See [Conversation-First Profile Workspace](profile-workspace-design.md).

Deferred profile work:

- Real file upload.
- Model connector integration.
- Structured output validation against production profile contracts.
- Database persistence.
- Human approval and publication workflow.

Recommended next step: connect the mocked conversation turn boundary to the model connector with structured validation while keeping tests on the mock adapter.

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
