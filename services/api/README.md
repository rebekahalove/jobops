# JobOps API

FastAPI backend scaffold for JobOps.

Initial scaffold status:

- Local-only.
- No database connection.
- No auth.
- No scraping.
- No email integration.
- Mock profile, Q&A, and role-fit endpoints only.

Run from this directory after installing Python 3.12:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -e .[dev]
py -m uvicorn jobops_api.main:app --reload --port 8000
```

