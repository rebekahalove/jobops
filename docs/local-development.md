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
- Python 3.12 if you want to run the FastAPI scaffold.

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

## Run The API Scaffold

The API scaffold is optional for this first local run.

From `services/api`:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -e .[dev]
py -m uvicorn jobops_api.main:app --reload --port 8000
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

The scaffold does not connect to the database yet. Keep the Neon connection string in `.env.dev`; it is ignored by Git and reserved for the first database increment.
