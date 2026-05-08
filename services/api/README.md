# JobOps API

FastAPI backend scaffold for JobOps.

Initial scaffold status:

- Local-only.
- SQLAlchemy and Alembic database layer wired for Neon Postgres.
- No auth.
- No scraping.
- No email integration.
- Mock profile, Q&A, and role-fit endpoints only.

Run from this directory after installing Python 3.14:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m uvicorn jobops_api.main:app --reload --port 8000
```

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
