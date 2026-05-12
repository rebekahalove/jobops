# JobOps Dashboard

Private JobOps dashboard shell for profile setup and future job-search workflows.

```powershell
corepack pnpm dev:jobops
```

Then open:

```text
http://localhost:3002
```

On Windows, run long-lived dev servers in a dedicated terminal. If starting this command from `cmd.exe` or a script, use `call corepack pnpm dev:jobops` so the parent shell stays alive. See [Local Development](../../docs/local-development.md) for the full local server checklist.

## Profile Workspace Shell

The `/profile` page includes the first conversation-first profile intake slice:

- Large chat/intake panel at the top of the page.
- Message input prefilled with `I want to be a...`.
- Resume attachment affordance with local metadata only.
- Resume text paste directly inside the chat message box.
- Server-side profile intake boundary that calls `@jobops/model-connector`.
- Mock provider support for deterministic local/test behavior.
- Live Gemini support when `JOBOPS_LLM_PROVIDER=gemini` and `GEMINI_API_KEY` are configured server-side.
- Structured output validation before draft state is updated.
- Structured profile review/edit surface below the conversation.

Generated data is always treated as:

- `draft`
- `needs_review`
- source-labeled as `chat`, `resume`, or `model`
- `private`
- `published: false`

Review queues are grouped by information type rather than status. Approval, public-ready, and publish controls are intentionally deferred.

See [Conversation-First Profile Workspace](../../docs/profile-workspace-design.md).

## Profile Intake Model Modes

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
- Database persistence.
- Permanent raw resume storage.
- Full profile generator agent loop.
- Human approval workflow.
- Public fact publication.
- Job intake, fit scoring, materials generation, and application tracking.

Recommended next step: persist validated draft intake output behind the API/database boundary, with explicit review and verification actions.
