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

`JOBOPS_DEFAULT_CANDIDATE_PROFILE_SLUG` is the local-dev profile context used before auth exists. Profile intake defaults to `rebekah-love` if it is not set.

## Production

Production secrets should be configured in platform environment variables:

- Render for the FastAPI backend.
- Netlify for frontend-only public values and build-time settings.
- GitHub Actions for CI secrets.
- Neon for database credentials and connection details.

Production should not rely on a committed `.env.prod` file. A local `.env.prod` may exist for controlled testing, but it must remain ignored.

## Testing

Tests should prefer isolated test configuration:

- `APP_ENV=test`
- A disposable local or CI Postgres database.
- Mock model provider unless the test is explicitly a live-model eval.

CI should not need the user's local `.env.dev` file.
