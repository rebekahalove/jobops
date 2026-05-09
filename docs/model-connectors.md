# Model Connectors

JobOps uses a provider-agnostic model connector layer so agent workflows do not depend directly on a single LLM provider SDK.

The connector lives in:

```text
packages/model-connector
```

Future packages such as `packages/agents`, `packages/evals`, and `packages/security-harness` should call this package instead of importing provider SDKs directly.

## Goals

- Keep provider-specific SDKs isolated from app and agent code.
- Support deterministic local tests with a mock adapter.
- Support live local development with Gemini.
- Route model calls by task type.
- Parse and validate structured model output before use.
- Keep API keys server-side.

## Providers

Initial providers:

- `mock`: deterministic adapter for tests, local workflows, and CI.
- `gemini`: live adapter using `@google/genai`.

OpenAI remains a future provider option through the shared connector interface, but it is not implemented in this branch.

## Default Models

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

Task-specific overrides can be added through `taskModelOverrides` when a workflow needs a different model.

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
- Browser/client bundles must not import `@jobops/model-connector/server`.
- Tests should use the mock adapter and should not require live API keys.

## Safety Contract

Model inputs may include resumes, job descriptions, chat messages, or recruiter-provided text. Treat all of that text as untrusted data, not instructions.

Connector users should:

- Keep system/developer instructions separate from user-provided content.
- Never let model output directly become a verified or published profile fact.
- Parse and validate structured output before use.
- Preserve provenance for extracted claims.
- Keep prompt-injection and regression tests close to workflows that use untrusted text.

The connector includes `generateStructuredOutput` and validation helpers so agent workflows have a single place to enforce JSON parsing and schema-like validation.

## Usage

Deterministic test usage:

```ts
import { MockModelConnector, createDefaultRoutingConfig } from "@jobops/model-connector";

const connector = new MockModelConnector({
  ...createDefaultRoutingConfig(),
  defaultResponse: "{\"facts\":[]}"
});
```

Server-side live usage:

```ts
import { createModelConnector, readModelConnectorConfigFromEnv } from "@jobops/model-connector/server";

const connector = createModelConnector(readModelConnectorConfigFromEnv());
```

The server export is intentionally separate so provider SDKs and secret-reading code stay away from client components and public browser bundles.
