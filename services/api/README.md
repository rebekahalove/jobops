# JobOps API

FastAPI backend scaffold for JobOps.

Initial scaffold status:

- Local-only.
- SQLAlchemy and Alembic database layer wired for Neon Postgres.
- Shared Python model connector with mock and optional Gemini providers.
- Profile-intake extraction endpoint with Pydantic validation, local debug artifacts, and DB-backed draft persistence.
- No auth.
- No scraping.
- No email integration.
- Mock public profile, Q&A, and role-fit endpoints.

Run from this directory after installing Python 3.14:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m uvicorn jobops_api.main:app --reload --port 8000
```

Health check:

```text
http://localhost:8000/health
```

## Docker

This Docker setup packages only the existing FastAPI service under `services/api`. It does not deploy the backend and does not change the frontend hosting model.

From the repo root, build the local API image:

```powershell
docker build -t jobops-api:local -f services/api/Dockerfile services/api
```

Run the container with local environment files:

```powershell
docker run --rm --env-file .env --env-file .env.dev -p 8000:8000 jobops-api:local
```

Or run it with Docker Compose:

```powershell
docker compose up --build api
```

Check the containerized API:

```powershell
Invoke-WebRequest -Uri http://localhost:8000/health -UseBasicParsing
```

The default local database path still uses Neon via `DATABASE_URL` in `.env.dev`. There is no local Postgres container in this compose file; that keeps local behavior aligned with the Neon-first workflow. If a local database is added later, it should be optional and use the same SQLAlchemy/Alembic migration path.

Apply Alembic migrations explicitly. From the host:

```powershell
python -m alembic upgrade head
```

Or from a one-off container:

```powershell
docker compose run --rm api python -m alembic upgrade head
```

The container uses the same `jobops_api.main:app` entry point as local development and binds Uvicorn to `0.0.0.0:8000`.

## Profile Intake

The active profile-intake backend is:

```text
POST /v1/profile-intake/extract
```

Request body:

```json
{
  "latest_user_message": "I want to be an Applied AI Engineer...",
  "existing_draft": null,
  "candidate_profile_slug": "rebekah-love"
}
```

The endpoint owns prompt construction, JSON parsing, Pydantic validation, local artifact saving, server-side debug logging, and persistence of validated draft data. It calls the shared Python model connector in `jobops_api/model_connector/` for provider selection, model routing, and model calls. Next.js should call this endpoint directly or through its thin proxy.

Mock mode:

```text
JOBOPS_LLM_PROVIDER=mock
```

Live Gemini mode:

```text
JOBOPS_LLM_PROVIDER=gemini
GEMINI_API_KEY=your_local_key
JOBOPS_DEFAULT_MODEL=gemini-2.5-flash
```

All extracted data remains draft or needs review, private, unpublished, and unverified. The endpoint persists only validated draft profile data and safe/redacted intake events. It does not store raw resume or chat text by default.

Local debug artifacts:

```text
JOBOPS_PROFILE_INTAKE_SAVE_ARTIFACTS=true
JOBOPS_PROFILE_INTAKE_SAVE_RAW_TEXT=false
```

Artifacts are written to `artifacts/profile-intake/<timestamp>_<run_id>/`. Enable raw text only for local debugging because `prompt.txt` and `raw-response.txt` may contain resume or chat content.

## Database

The API reads `.env`, then `.env.<APP_ENV>`, so local development can keep the Neon URL in `.env.dev`.

Apply migrations:

```powershell
python -m alembic upgrade head
```

Seed the first public candidate profile shell:

```powershell
python -m jobops_api.cli seed-public-profile --hostname rebekahalove.dev
```

The seed command creates the tenant, candidate profile, and optional domain mapping. It does not create private facts or publish unreviewed facts.

Profile intake persistence uses these existing tables where practical:

- `profile_intake_sessions`
- `role_targets`
- `profile_fact_drafts`
- `skill_claims`
- `evidence_artifacts`

This slice also adds:

- `profile_intake_events` for redacted user/assistant/model events.
- `experience_project_drafts` for draft experience and project items.

The active session uses replacement behavior for now: each successful model turn replaces the current draft facts, skills, experience/projects, evidence, and target role intent for that intake session. Review controls, approval/rejection, publication, auth, and durable raw resume storage are deferred.
