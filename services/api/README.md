# JobOps API

FastAPI backend scaffold for JobOps.

Initial scaffold status:

- Local-only.
- SQLAlchemy and Alembic database layer wired for Neon Postgres.
- Shared Python model connector with mock and optional Gemini providers.
- Profile-intake extraction endpoint with Pydantic validation, local debug artifacts, and DB-backed draft persistence.
- Temporary internal API key protection for private/write/model/draft endpoints.
- No full user auth.
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

## Internal API Key

The backend keeps public read endpoints open:

```text
GET /health
GET /v1/profiles/{slug}
GET /v1/profile-by-hostname/{hostname}
```

Private, write, model, draft, command-center, and application-tracking endpoints require:

```text
X-JobOps-Internal-Key: <JOBOPS_INTERNAL_API_KEY>
```

In `APP_ENV=prod`, `JOBOPS_INTERNAL_API_KEY` is required and protected endpoints fail closed if it is missing. In local development, protected endpoints remain open when no key is configured; once a key is configured, local callers must send it too.

For Render production:

```text
APP_ENV=prod
JOBOPS_INTERNAL_API_KEY=<long random secret>
JOBOPS_CORS_ORIGINS=https://rebekahalove.dev,https://www.rebekahalove.dev,https://jobops.rebekahalove.dev
```

The same `JOBOPS_INTERNAL_API_KEY` must be configured in Netlify for server-side Next.js proxy routes. Do not use a `NEXT_PUBLIC_*` variable for this key.

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

Profile intake is stateful from the backend's perspective. When a database session is available, FastAPI resolves the candidate profile and active intake session, loads the authoritative saved draft snapshot from Postgres, and injects it into the model prompt as `authoritative_current_draft`. The request field `existing_draft` is still accepted for compatibility and UI/debug context, but it is labeled non-authoritative and must not override the database-loaded draft.

Each model turn should be treated as an incremental update to the saved draft, not a replacement profile. The model, not the persistence layer, is responsible for semantically merging the latest message into `authoritative_current_draft`. For `targetRoleIntent`, any non-empty field the model returns is treated as the final post-update value for that field. If the user broadens a preference, including terse wording like "or NYC or San Francisco Bay", the model should copy existing values and include the new values in the same output field. Explicit replacement language such as "instead", "not X anymore", "change X to Y", "remove X", or "clear X" may update or remove values only when that intent is clear. Empty model output fields mean "no change" for existing saved data, not "clear this field".

Location-like target role fields remain string-backed for now. The model should return merged strings such as `Louisville, KY; London, UK` when updating semicolon-delimited location lists. TODO: list-like target role fields should become structured arrays once the DB/UI contract can support that cleanly.

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

The active session uses merge behavior: each successful model turn applies a patch to the current draft facts, skills, experience/projects, evidence, and target role intent for that intake session. Review controls, approval/rejection, publication, auth, and durable raw resume storage are deferred.

Published profile rows must not be mutated directly by profile intake. When no active draft exists but a published role target or published profile facts exist, the backend seeds a private, unpublished intake draft copy before applying new model-generated changes. Broader published-profile edit UX, including asking whether to start from scratch or from the previous published profile, remains deferred.
