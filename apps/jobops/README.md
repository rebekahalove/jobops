# JobOps Dashboard

Private JobOps dashboard shell for an AI-first job-search command center.

```powershell
corepack pnpm dev:jobops
```

Then open:

```text
http://localhost:3002
```

On Windows, run long-lived dev servers in a dedicated terminal. If starting this command from `cmd.exe` or a script, use `call corepack pnpm dev:jobops` so the parent shell stays alive. See [Local Development](../../docs/local-development.md) for the full local server checklist.

## AI Command Center Shell

The private app now centers on one JobOps command panel at the top of the shell, with workspace tabs below it:

- Profile
- Companies
- Jobs
- Applications
- Materials
- Follow-ups

For this branch, the command center is intentionally local and mocked. It classifies commands into planned action cards but does not execute tools, fetch job URLs, call models, scrape pages, generate materials, or automate a browser.

Real command handling should go through FastAPI. FastAPI owns agent command routing, tool execution, model calls, job URL intake, company follow, fit analysis, materials generation, and persistence. Next.js remains UI and thin proxy only.

See [AI Command Center Shell](../../docs/ai-command-center-shell.md).

## Profile Workspace Shell

The `/profile` page includes the first conversation-first profile intake slice:

- Large chat/intake panel at the top of the page.
- Message input prefilled with `I want to be a...`.
- Resume attachment affordance with local metadata only.
- Resume text paste directly inside the chat message box.
- Thin Next.js API proxy to the FastAPI profile-intake endpoint.
- Mock provider support in FastAPI for deterministic local/test behavior.
- Live Gemini support in FastAPI when `JOBOPS_LLM_PROVIDER=gemini` and `GEMINI_API_KEY` are configured server-side.
- Pydantic structured output validation before draft state is updated.
- DB-backed persistence for validated draft profile data and redacted intake events.
- Structured profile review/edit surface below the conversation.

Generated data is always treated as:

- `draft`
- `needs_review`
- source-labeled as `chat`, `resume`, or `model`
- `private`
- `published: false`

Review queues are grouped by information type rather than status. The saved draft snapshot remains local-dev/profile-scoped until auth exists. Approval, public-ready, and publish controls are intentionally deferred.

See [Conversation-First Profile Workspace](../../docs/profile-workspace-design.md).

## Profile Intake Model Modes

The JobOps app expects the FastAPI service to be running at `JOBOPS_API_BASE_URL`, usually `http://localhost:8000`.
Next.js owns the UI and proxy only; prompt construction, model calls, validation, persistence, debug logging, and local artifact saving live in `services/api`. Shared provider/model routing lives in the Python `jobops_api.model_connector` module.

Mock mode, recommended for local UI work and tests:

```text
APP_ENV=dev
JOBOPS_LLM_PROVIDER=mock
JOBOPS_DEFAULT_MODEL=gemini-2.5-flash
JOBOPS_CHEAP_MODEL=gemini-2.5-flash-lite
```

Live Gemini mode:

```text
APP_ENV=dev
JOBOPS_LLM_PROVIDER=gemini
GEMINI_API_KEY=your_local_key
JOBOPS_DEFAULT_MODEL=gemini-2.5-flash
JOBOPS_CHEAP_MODEL=gemini-2.5-flash-lite
```

Keep provider keys in ignored local files such as `.env.dev`; never prefix them with `NEXT_PUBLIC_`.

## Local Intake Debug Artifacts

To inspect malformed live model output locally:

```text
JOBOPS_PROFILE_INTAKE_SAVE_ARTIFACTS=true
JOBOPS_PROFILE_INTAKE_SAVE_RAW_TEXT=false
```

Artifacts are written to `artifacts/profile-intake/<timestamp>_<runId>/` and are gitignored. Raw prompt/response capture is off by default. Set `JOBOPS_PROFILE_INTAKE_SAVE_RAW_TEXT=true` only when debugging locally, because raw artifacts may contain resume or chat content.

## Intentionally Deferred

- Authentication.
- Permanent raw resume storage.
- Full profile generator agent loop.
- Human approval workflow.
- Public fact publication.
- Real command execution.
- Job URL fetching/extraction.
- Company discovery/search.
- Job prioritization.
- Fit analysis.
- Materials generation.
- Browser automation.

Recommended next step: add a FastAPI command-routing endpoint that returns typed planned actions without executing external tools.
