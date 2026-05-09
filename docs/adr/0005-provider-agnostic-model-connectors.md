# ADR 0005: Provider-Agnostic Model Connectors

Status: Accepted

## Context

JobOps will use model calls across the public candidate-agent portfolio, future profile intake workflows, role-fit analysis, application packet drafting, evals, and prompt-injection tests.

The system should not wire agent workflows directly to one provider SDK. It also needs deterministic tests, clear routing by task type, safe handling for API keys, and structured-output validation before model output can influence profile data.

The next milestone is a resume-augmented Profile Intake Agent. Resume text, job descriptions, and user chat messages are untrusted data and must not be allowed to override system behavior or directly publish candidate facts.

## Decision

Create a separate package:

```text
packages/model-connector
```

This package owns:

- Provider-neutral model request and response types.
- Task-based model routing.
- A deterministic mock adapter.
- A Gemini adapter using `@google/genai`.
- Server-side environment config helpers.
- Structured-output parsing and validation hooks.

Initial model choices:

- Default live provider: Gemini.
- Default model: `gemini-2.5-flash`.
- Cheap/eval/bulk model: `gemini-2.5-flash-lite`.

OpenAI remains a future provider option through the connector interface, but it is not implemented now.

## Consequences

Positive:

- Agents can depend on a stable connector interface instead of provider SDK details.
- Tests and CI can use deterministic mock behavior with no live API calls.
- Provider SDK imports and API-key reads stay isolated to server-side connector exports.
- The same routing layer can support future profile intake, role-fit, eval, and safety harness workflows.
- Structured-output validation becomes a first-class boundary before generated data is used.

Tradeoffs:

- The repository adds one more internal package.
- The connector adds `@google/genai` as a dependency before the first live workflow uses it.
- App code must respect the server/client split and avoid importing `@jobops/model-connector/server` from browser-facing modules.

## Safety Notes

- Treat resumes, job descriptions, and user-provided chat content as untrusted input.
- Model output may propose draft facts, but it must not create verified or published facts directly.
- Human review and explicit publication remain required before facts can power public candidate-agent responses.
- Prompt-injection tests and eval harnesses should use this connector so provider behavior can be swapped without rewriting workflows.
