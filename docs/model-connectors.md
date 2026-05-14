# Model Connectors

JobOps uses a provider-agnostic model connector layer so model-backed workflows do not depend directly on a single LLM provider.

The project-wide connector now lives in FastAPI/Python:

```text
services/api/jobops_api/model_connector/
```

The original TypeScript `packages/model-connector` spike has been superseded and removed. React/Next.js code should call FastAPI endpoints, not model providers directly. Thin Next.js proxy routes are allowed when they only forward requests and responses.

## Goals

- Keep provider-specific HTTP/API details isolated from workflow code.
- Support deterministic local tests with a mock provider.
- Support live local development with Gemini.
- Route model calls by task type.
- Keep API keys server-side.
- Let each workflow own its own prompt, schema validation, and artifact policy.

## Connector Structure

```text
services/api/jobops_api/model_connector/
  config.py
  errors.py
  models.py
  providers.py
  routing.py
```

Core concepts:

- `ModelMessage`: provider-neutral message with `system`, `user`, or `assistant` role.
- `ModelRequest`: task, messages, optional model, temperature, token budget, response MIME type, and metadata.
- `ModelResponse`: text, provider, resolved model, finish reason, optional usage, and metadata.
- `ModelProvider`: provider protocol implemented by mock and Gemini providers.
- `ModelConnector`: routes a request to the right model, then calls the configured provider.

## Providers

Initial providers:

- `mock`: deterministic provider for tests, local workflows, and CI.
- `gemini`: live provider using Gemini's REST API from FastAPI server-side code.

OpenAI remains a future provider option through the shared Python connector interface, but it is not implemented yet.

## Task Routing

Default model settings:

```text
JOBOPS_DEFAULT_MODEL=gemini-2.5-flash
JOBOPS_CHEAP_MODEL=gemini-2.5-flash-lite
```

Task routing:

| Task | Model |
| --- | --- |
| `profile_extract` | default model |
| `intake_followup` | default model |
| `role_fit` | default model |
| `bulk_triage` | cheap model |
| `eval_harness` | cheap model |
| `judge_or_second_pass` | default model |

## Environment Variables

Server-side values:

```text
JOBOPS_LLM_PROVIDER=gemini
JOBOPS_DEFAULT_MODEL=gemini-2.5-flash
JOBOPS_CHEAP_MODEL=gemini-2.5-flash-lite
GEMINI_API_KEY=...
```

Rules:

- `GEMINI_API_KEY` belongs only in ignored local files such as `.env.dev` or platform secret stores.
- Do not prefix model secrets with `NEXT_PUBLIC_`.
- Browser/client bundles must not import model provider code.
- Tests should use the mock provider and should not require live API keys.

## Profile Intake Usage

The active profile-intake runtime path is:

```text
AI Command Center UI
-> Next.js /api/command-center proxy
-> FastAPI POST /v1/command-center/commands
-> profile_intake service
-> shared Python model_connector
-> configured provider
```

The older `/api/profile-intake` and `/v1/profile-intake/extract` boundaries remain available as a direct workflow endpoint, but the primary JobOps product flow is command center -> FastAPI command routing -> `profile_intake`.

Profile intake owns its prompt, Pydantic output schema, artifact saving, validation behavior, and profile-specific mock response. The shared connector owns provider-neutral request/response types, task routing, provider creation, mock provider behavior, and Gemini HTTP behavior.

The profile intake contract requires generated facts, skill claims, experience/project items, and evidence links to remain private, unpublished, and marked for review. Model output cannot become verified, public, or published data through this boundary.

## Local Profile Intake Artifacts

Profile intake can save local debugging artifacts for malformed JSON or validation failures:

```text
JOBOPS_PROFILE_INTAKE_SAVE_ARTIFACTS=true
JOBOPS_PROFILE_INTAKE_SAVE_RAW_TEXT=false
```

Artifacts are written to:

```text
artifacts/profile-intake/<timestamp>_<runId>/
```

With raw text disabled, artifacts contain metadata, input sizes/counts, run IDs, provider/model names, latency, finish reason, validation issues, and parsed structured output when parsing succeeds. They do not contain full prompts, raw resume/chat prompts, raw model responses, or API keys.

Set `JOBOPS_PROFILE_INTAKE_SAVE_RAW_TEXT=true` only for local debugging when you need `prompt.txt` and `raw-response.txt`. Raw artifacts may contain resume/chat content and must remain local. `artifacts/` is gitignored.
