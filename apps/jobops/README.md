# JobOps Dashboard

Private JobOps dashboard shell for profile setup and future job-search workflows.

```powershell
corepack pnpm dev:jobops
```

Then open:

```text
http://localhost:3002
```

## Profile Workspace Shell

The `/profile` page includes the first local-only conversation-first profile intake shell:

- Large chat/intake panel at the top of the page.
- Message input prefilled with `I want to be a...`.
- Resume attachment affordance with local metadata only.
- Resume text paste directly inside the chat message box.
- Mock agent turn that updates target role intent, draft facts, skill claims, experience summaries, change summaries, and clarifying questions.
- Structured profile review/edit surface below the conversation.

The mock extractor marks all generated facts as:

- `draft`
- `resume_derived` or `chat_derived`
- `not_verified`
- `private`

Review queues are grouped by information type rather than status. Approval, public-ready, and publish controls are intentionally deferred.

See [Conversation-First Profile Workspace](../../docs/profile-workspace-design.md).

## Intentionally Deferred

- Authentication.
- Database persistence.
- Resume file upload.
- Live Gemini or model-provider calls.
- Full profile generator agent loop.
- Human approval workflow.
- Public fact publication.
- Job intake, fit scoring, materials generation, and application tracking.

Recommended next step: wire the mocked conversation turn boundary to `@jobops/model-connector` with structured-output validation while keeping tests on the mock adapter.
