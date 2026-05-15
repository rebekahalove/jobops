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
JOBOPS_DASHBOARD_PASSWORD=replace-with-local-preview-password
JOBOPS_DASHBOARD_COOKIE_SECRET=replace-with-long-local-random-secret
JOBOPS_CORS_ORIGINS=http://localhost:3000,http://localhost:3001,http://localhost:3002
JOBOPS_DEFAULT_CANDIDATE_PROFILE_SLUG=rebekah-love
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

`JOBOPS_DASHBOARD_PASSWORD` and `JOBOPS_DASHBOARD_COOKIE_SECRET` are read only by Next.js server code. They protect the private JobOps dashboard and its thin API proxy routes with a temporary private-preview gate. They must never be prefixed with `NEXT_PUBLIC_`. The gate sets a signed HttpOnly cookie and does not store the raw password in the browser.

For local development only, `JOBOPS_DASHBOARD_AUTH_DISABLED=true` may bypass the dashboard gate. The default is fail closed when the password or cookie secret is missing, and the bypass is ignored in production.

This dashboard gate is not full authentication. It does not support users, roles, password reset, account recovery, tenant isolation, audit trails, or per-user authorization. It is acceptable while the project is not intentionally shared, but it must be upgraded before publicly sharing the JobOps dashboard, onboarding other users, storing other people's private data, or using JobOps as a real multi-tenant product. The future replacement should be proper user authentication and authorization, likely owner-only auth first, then tenant/user auth later.

`JOBOPS_CORS_ORIGINS` is a comma-separated allowlist of browser origins allowed to call the FastAPI backend. Values are trimmed and empty items are ignored.

`JOBOPS_DEFAULT_CANDIDATE_PROFILE_SLUG` is the local-dev profile context used before auth exists. Profile intake defaults to `rebekah-love` if it is not set.

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
JOBOPS_DASHBOARD_PASSWORD=<temporary private-preview password>
JOBOPS_DASHBOARD_COOKIE_SECRET=<long random secret>
```

`JOBOPS_INTERNAL_API_KEY` must be identical on Netlify and Render. It is a temporary server-to-server protection layer for private/write/model/draft endpoints, not a replacement for future user auth.

`JOBOPS_DASHBOARD_PASSWORD` and `JOBOPS_DASHBOARD_COOKIE_SECRET` are Netlify-only for the current dashboard gate. They do not replace the Render `JOBOPS_INTERNAL_API_KEY`; both layers are required until proper product authentication replaces the temporary private-preview gate.

## Testing

Tests should prefer isolated test configuration:

- `APP_ENV=test`
- A disposable local or CI Postgres database.
- Mock model provider unless the test is explicitly a live-model eval.

CI should not need the user's local `.env.dev` file.
