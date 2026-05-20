# Environment Configuration

JobOps uses a two-step local environment loading strategy.

The root `.env` file selects the active local environment:

```text
APP_ENV=dev
```

Then the environment loader reads:

```text
.env.<APP_ENV>
```

For local development, that means:

```text
.env      -> contains APP_ENV=dev
.env.dev  -> contains the dev Neon connection string and other local secrets
```

The deployed FastAPI API has a temporary server-to-server protection layer for private endpoints. It is an internal API key shared only by the frontend server environment and the backend API environment. It is not full user authentication.

## Files

Committed examples:

- `.env.example`
- `.env.dev.example`
- `.env.prod.example`

Ignored local secret files:

- `.env`
- `.env.dev`
- `.env.prod`
- `.env.*`

Do not commit real database URLs, API keys, tokens, cookies, or model provider keys.

## Loader Rules

The shared environment utility should:

1. Load `.env` from the repo root.
2. Read and validate `APP_ENV`.
3. Load `.env.<APP_ENV>` from the repo root.
4. Let explicit process environment variables override file values.
5. Fail fast if required values are missing.
6. Never print secret values in logs or error messages.

`APP_ENV` must be a simple environment name such as:

```text
dev
test
preview
prod
```

The loader must reject path-like values such as `../prod` or absolute paths.

## Local Development

Recommended local setup:

```text
.env
.env.dev
```

`.env` should contain only:

```text
APP_ENV=dev
```

`.env.dev` may contain:

```text
DATABASE_URL=...
JOBOPS_API_BASE_URL=http://localhost:8000
JOBOPS_INTERNAL_API_KEY=replace-with-local-dev-secret
JOBOPS_CORS_ORIGINS=http://localhost:3000,http://localhost:3001,http://localhost:3002
JOBOPS_LLM_PROVIDER=mock
JOBOPS_PROFILE_INTAKE_SAVE_ARTIFACTS=false
JOBOPS_PROFILE_INTAKE_SAVE_RAW_TEXT=false
```

The real Neon connection string belongs in `.env.dev`, not in `.env.example`, docs, tests, or committed fixtures.

Profile intake artifact flags are local debugging controls:

- `JOBOPS_PROFILE_INTAKE_SAVE_ARTIFACTS=true` writes metadata artifacts under `artifacts/profile-intake/`.
- `JOBOPS_PROFILE_INTAKE_SAVE_RAW_TEXT=true` also writes prompts and raw model responses. These may include resume or chat content and should stay local.

`JOBOPS_API_BASE_URL` points frontend server code at the FastAPI service. The JobOps dashboard uses it for the profile-intake proxy, and the portfolio app uses it for public profile reads when the API is running locally.

`JOBOPS_INTERNAL_API_KEY` is read only by server-side code. It must never be prefixed with `NEXT_PUBLIC_` or passed to client components. In local development, protected FastAPI endpoints are open when no internal key is configured; once the key is configured, calls must include `X-JobOps-Internal-Key`.

For local development only, `JOBOPS_DASHBOARD_AUTH_DISABLED=true` may bypass the dashboard session gate. The bypass is ignored in production.

The dashboard uses alpha username/session auth. It is still not full SaaS authentication: it does not support password reset, account recovery, OAuth, billing, complex RBAC, or polished onboarding. Persist initial users with `jobops_api.cli seed-initial-user`; do not store default user/profile identity in `.env`.

`JOBOPS_CORS_ORIGINS` is a comma-separated allowlist of browser origins allowed to call the FastAPI backend. Values are trimmed and empty items are ignored.

## Production

Production secrets should be configured in platform environment variables:

- Render for the FastAPI backend.
- Netlify for frontend-only public values and build-time settings.
- GitHub Actions for CI secrets.
- Neon for database credentials and connection details.

Production should not rely on a committed `.env.prod` file. A local `.env.prod` may exist for controlled testing, but it must remain ignored.

Required Render backend values:

```text
APP_ENV=prod
JOBOPS_INTERNAL_API_KEY=<long random secret>
JOBOPS_CORS_ORIGINS=https://rebekahalove.dev,https://www.rebekahalove.dev,https://jobops.rebekahalove.dev
```

No Render change is required for the dashboard gate. Existing backend security variables, `DATABASE_URL`, model provider, and model API key settings remain unchanged. In `APP_ENV=prod`, `/docs`, `/redoc`, and `/openapi.json` are disabled by default. Set `JOBOPS_ENABLE_API_DOCS=true` only when intentionally exposing FastAPI docs.

Required Netlify frontend server values:

```text
JOBOPS_API_BASE_URL=https://api.rebekahalove.dev
JOBOPS_INTERNAL_API_KEY=<same long random secret as Render>
```

`JOBOPS_INTERNAL_API_KEY` must be identical on Netlify and Render. It is a temporary server-to-server protection layer for private/write/model/draft endpoints, not a replacement for future user auth.

JobOps dashboard access uses persisted users and the backend `jobops_session` cookie. `JOBOPS_INTERNAL_API_KEY` remains server-only protection between Next.js routes and FastAPI.

## Testing

Tests should prefer isolated test configuration:

- `APP_ENV=test`
- A disposable local or CI Postgres database.
- Mock model provider unless the test is explicitly a live-model eval.

CI should not need the user's local `.env.dev` file.
