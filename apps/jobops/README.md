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

The `/profile` page includes the first local-only profile intake shell:

- Target role intent fields.
- Resume text paste area.
- Disabled resume upload placeholder.
- Deterministic mock draft profile extraction.
- Draft profile preview.
- Clarifying questions for applied AI, forward-deployed, and LLM systems profiles.

The mock extractor marks all generated facts as:

- `draft`
- `resume_derived`
- `not_verified`
- `private`

Human-approved facts and public/published facts intentionally remain empty.

## Intentionally Deferred

- Authentication.
- Database persistence.
- Resume file upload.
- Live Gemini or model-provider calls.
- Full profile generator agent loop.
- Human approval workflow.
- Public fact publication.
- Job intake, fit scoring, materials generation, and application tracking.

Recommended next step: wire this mock extractor boundary to `@jobops/model-connector` using structured-output validation, still with the mock adapter first.
