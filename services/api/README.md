# JobOps API

FastAPI backend scaffold for JobOps.

Initial scaffold status:

- Local-only.
- SQLAlchemy and Alembic database layer wired for Neon Postgres.
- Shared Python model connector with mock and optional Gemini providers.
- Profile-intake extraction endpoint with Pydantic validation and local debug artifacts.
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

## Profile Intake

The active profile-intake backend is:

```text
POST /v1/profile-intake/extract
```

Request body:

```json
{
  "latest_user_message": "I want to be an Applied AI Engineer...",
  "existing_draft": null
}
```

The endpoint owns prompt construction, JSON parsing, Pydantic validation, local artifact saving, and server-side debug logging. It calls the shared Python model connector in `jobops_api/model_connector/` for provider selection, model routing, and model calls. Next.js should call this endpoint directly or through its thin proxy.

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

All extracted data remains draft, private, unpublished, and unverified. The endpoint does not persist raw resume text or generated draft profile data yet.

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
