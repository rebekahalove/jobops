# Application Tracker MVP

The first Application Tracker slice is manual-entry only. It is meant to make JobOps useful for active job search tracking before job posting intake, fit scoring, and generated materials are ready.

## Supported Now

- Add an application by entering company, job title, job URL, location, source, date applied, status, notes, and next follow-up date.
- List saved applications for the default candidate profile.
- Update application status.
- Add timeline events through the FastAPI endpoint.
- Store application data in Postgres-managed SQLAlchemy/Alembic tables.

Application statuses:

- `saved`
- `applied`
- `interviewing`
- `rejected`
- `offer`
- `closed`
- `withdrawn`

## Database Tables

- `companies`: canonical company records shared across profiles.
- `candidate_companies`: profile-specific followed-company links with private notes/status.
- `job_roles`: manually entered or future-ingested roles tied to a candidate profile and optionally a canonical company.
- `applications`: the application tracking record, including denormalized company/job text for quick list rendering.
- `application_events`: timeline entries for follow-ups, interviews, notes, and status-related activity.

## API Endpoints

FastAPI owns the tracker behavior:

```text
POST /v1/applications
GET /v1/applications
PATCH /v1/applications/{application_id}/status
POST /v1/applications/{application_id}/events
```

The JobOps dashboard uses thin Next.js proxy routes under `/api/applications` so the browser does not need to call FastAPI directly.

## Intentionally Deferred

- Job posting extraction.
- Fit scoring.
- Cover letter generation.
- Email or Gmail integration.
- Reminders and notifications.
- OAuth, teams/RBAC, and account recovery beyond alpha sessions.
- Scraping or browser automation.

## Local Run

Start FastAPI and the JobOps dashboard:

```powershell
cd C:\Users\rasho\jobops\services\api
.\.venv\Scripts\Activate.ps1
python -m uvicorn jobops_api.main:app --reload --port 8000
```

```powershell
cd C:\Users\rasho\jobops
corepack pnpm dev:jobops
```

Open:

```text
http://localhost:3002/applications
```
