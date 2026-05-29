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

Safe build metadata:

```text
http://localhost:8000/v1/version
```

`/v1/version` returns only public support metadata such as app name, release channel, environment, and short commit SHA. It recognizes safe deployment variables like `COMMIT_REF`, `RENDER_GIT_COMMIT`, and `GITHUB_SHA`, then falls back to local git metadata when available. It never returns secrets, database URLs, API keys, CORS config, or full environment dumps.

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

Profile intake uses a full-draft update contract. When a database session is available, FastAPI resolves the candidate profile and active intake session, loads the authoritative saved draft snapshot from Postgres, and injects it into the model prompt as `authoritative_current_draft`. The request field `existing_draft` is still accepted for compatibility and UI/debug context, but it is labeled non-authoritative and must not override the database-loaded draft.

Each model turn returns `updatedDraftProfile`, the complete updated draft after applying the latest user instruction. The model, not the persistence layer, is responsible for semantically merging the latest message into `authoritative_current_draft`. If the user broadens a preference, including terse wording like "or NYC or San Francisco Bay", the model should copy existing values and include the new values in the returned full draft. If the instruction is ambiguous, the model should return the draft unchanged, include clarifying questions, and set `noChangeReason`.

The backend validates the full updated draft and synchronizes editable draft rows to match it. Existing items are matched by ID first; editable content fields may be updated, but review status, visibility, publication status, and published/approved metadata are preserved. New items omit IDs and are created as private unpublished drafts. Existing draft items omitted from `updatedDraftProfile` are preserved unless their IDs appear in `removedItems`, which keeps malformed or incomplete model output from deleting saved profile data.

Profile intake detects compact chat updates separately from resume-like input. Resume-like signals include explicit resume/CV wording, long pasted text with resume section headings, multiple role/date patterns, and section sets such as Experience, Education, Skills, Projects, or Certifications. Compact chat turns are prompted to stay small, while resume intake may use up to 32 facts, 50 skill claims, 18 experience/project items, 20 evidence links, 6 clarifying questions, and 12 change-summary entries. The Pydantic schema enforces those resume-mode caps.

Model requests use `max_output_tokens=5000` for compact chat updates and `max_output_tokens=16000` for resume intake or already-rich saved drafts. The 16000-token budget is intentionally practical rather than open-ended: it gives concise JSON enough room for the resume-mode caps while still bounding provider cost and response size. If a resume response still truncates, the API retries once with a smaller representative first pass capped at 6 facts, 10 skill claims, 5 experience/project items, 4 evidence links, 3 clarifying questions, and 4 change-summary entries with `max_output_tokens=8000`. If the provider still truncates output, the API returns `code: "model_response_truncated"` with a specific error and no draft data is applied. If the model exceeds schema capacity, the API returns `code: "model_output_exceeded_schema_capacity"` so local testing can distinguish capacity issues from malformed JSON.

In non-production environments, successful and failed profile-intake responses include `modelRequest` and `modelResponse` debug payloads so the UI can show both the full prompt sent to the provider and the raw model response while the workflow is still being built out. These debug payloads are omitted in production.

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

All model-generated data remains draft or needs review, private, unpublished, and unverified. The endpoint persists only validated draft profile data and safe/redacted intake events. It does not store raw resume or chat text by default.

Local debug artifacts:

```text
JOBOPS_PROFILE_INTAKE_SAVE_ARTIFACTS=true
JOBOPS_PROFILE_INTAKE_SAVE_RAW_TEXT=false
```

Artifacts are written to `artifacts/profile-intake/<timestamp>_<run_id>/`. Enable raw text only for local debugging because `prompt.txt` and `raw-response.txt` may contain resume or chat content.

## Job Discovery Providers

Command-center job discovery saves only jobs backed by live provider results, verified fetched pages, user-provided URLs, or explicit mock results. Freeform model output is not allowed to create canonical job postings.

Preferred provider configuration is a comma-separated list:

```text
JOBOPS_JOB_DISCOVERY_PROVIDERS=adzuna,greenhouse
JOBOPS_JOB_DISCOVERY_ALLOW_PARTIAL_PROVIDER_FAILURES=false
JOBOPS_JOB_DISCOVERY_RESULTS_PER_PROVIDER=20
```

`JOBOPS_JOB_DISCOVERY_SOURCE` is still accepted as a backward-compatible single-provider setting, but `JOBOPS_JOB_DISCOVERY_PROVIDERS` should be used for new environments. With no real provider configured outside mock mode, broad discovery returns `live_job_discovery_not_configured` and saves nothing.

Mock provider:

```text
JOBOPS_LLM_PROVIDER=mock
JOBOPS_JOB_DISCOVERY_PROVIDERS=mock
```

Adzuna broad-search provider:

```text
JOBOPS_JOB_DISCOVERY_PROVIDERS=adzuna
JOBOPS_ADZUNA_APP_ID=your_adzuna_app_id
JOBOPS_ADZUNA_APP_KEY=your_adzuna_app_key
JOBOPS_ADZUNA_COUNTRY=us
```

Greenhouse ATS-board provider:

```text
JOBOPS_JOB_DISCOVERY_PROVIDERS=greenhouse
JOBOPS_GREENHOUSE_BOARD_TOKENS=civicactions,exampleboard
```

Multiple providers can run in order:

```text
JOBOPS_JOB_DISCOVERY_PROVIDERS=adzuna,greenhouse
```

Job discovery diagnostics include configured providers, per-provider attempted/configured/result/error status, raw provider result count, deduped candidate count, verified URL count, saved count, duplicate count, skipped count, and grouped skipped reasons. Provider-backed URLs may be stored as `provider_unverified` when a trusted provider result exists but server-side fetch is blocked; obvious 404/410/dead links are skipped. Posting dates are stored only when supplied by the provider or fetched page.

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

The active session synchronizes the editable draft to the model-returned full `updatedDraftProfile`. Review controls, approval/rejection, publication, auth, and durable raw resume storage are deferred.

Published profile rows must not be mutated directly by profile intake. When no active draft exists but a published role target or published profile facts exist, the backend seeds a private, unpublished intake draft copy before applying new model-generated changes. Broader published-profile edit UX, including asking whether to start from scratch or from the previous published profile, remains deferred.
